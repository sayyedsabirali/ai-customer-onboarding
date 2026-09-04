import asyncio
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv()

backend_dir = str(Path(__file__).resolve().parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Fix Windows event loop policy for psycopg async
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from database.connection import DATABASE_URL, engine, SessionLocal
from database.models import Customer, OnboardingState
from agent.graph import build_onboarding_graph
from routes import onboarding, escalation
from utils.logger import setup_logging, get_logger, set_log_context, clear_log_context, get_log_context
from utils.rate_limiter import limiter

# Initialize structured JSON logger
setup_logging()
logger = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan: Open connection pool, setup checkpointer, compile graph.
    Shutdown: Close pool gracefully.
    """
    logger.info("Lifespan starting: opening connection pool and building graph", extra={"action": "startup"})
    app.state.start_time = time.time()

    pool = AsyncConnectionPool(
        DATABASE_URL,
        open=False,
        min_size=2,
        max_size=15,
        timeout=30,
        max_idle=300.0,
        check=AsyncConnectionPool.check_connection,
        kwargs={"autocommit": True}
    )
    await pool.open()
    logger.info("Postgres connection pool opened successfully", extra={"action": "pool_opened"})

    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()

    graph = build_onboarding_graph(checkpointer)
    logger.info("LangGraph agent workflow compiled successfully", extra={"action": "graph_compiled"})

    if os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true":
        project_name = os.getenv("LANGCHAIN_PROJECT", "flowai-onboarding")
        logger.info(f"LangSmith LLM observability enabled for project: {project_name}", extra={"action": "langsmith_init", "project": project_name})

    app.state.pool = pool
    app.state.checkpointer = checkpointer
    app.state.graph = graph

    yield

    logger.info("Lifespan shutting down: closing connection pool", extra={"action": "shutdown"})
    await pool.close()


app = FastAPI(
    title="AI Customer Onboarding Agent",
    description="Agentic Customer Onboarding System with LLM validation, SLA tracking, and HITL escalation.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# 1. Structured Logging & Latency Middleware
@app.middleware("http")
async def structured_logging_middleware(request: Request, call_next):
    start_time = time.time()
    session_id = request.query_params.get("session_id") or request.headers.get("X-Session-ID") or ""
    customer_id = request.query_params.get("customer_id") or request.headers.get("X-Customer-ID") or None

    # Check path parameters for customer_id or session_id
    path_parts = request.url.path.strip("/").split("/")
    if len(path_parts) >= 2 and path_parts[0] == "onboarding":
        if path_parts[1] == "dashboard" and len(path_parts) == 3:
            customer_id = customer_id or path_parts[2]
        elif path_parts[1] == "state" and len(path_parts) == 3:
            session_id = session_id or path_parts[2]
        elif path_parts[1] == "state" and len(path_parts) == 4 and path_parts[2] == "customer":
            customer_id = customer_id or path_parts[3]

    set_log_context(session_id=session_id, customer_id=customer_id)

    try:
        response: Response = await call_next(request)
        latency_ms = round((time.time() - start_time) * 1000, 2)

        # Retrieve resolved customer_id and session_id after route execution
        final_customer_id = getattr(request.state, "customer_id", None) or get_log_context().get("customer_id") or customer_id
        final_session_id = getattr(request.state, "session_id", None) or get_log_context().get("session_id") or session_id

        log_extra = {
            "method": request.method,
            "endpoint": request.url.path,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "session_id": final_session_id or ""
        }
        if final_customer_id:
            log_extra["customer_id"] = str(final_customer_id)

        # Log request with structured JSON fields
        logger.info(
            f"{request.method} {request.url.path} - {response.status_code} ({latency_ms}ms)",
            extra=log_extra
        )
        response.headers["X-Response-Time"] = f"{latency_ms}ms"
        return response
    except Exception as exc:
        latency_ms = round((time.time() - start_time) * 1000, 2)
        final_customer_id = getattr(request.state, "customer_id", None) or get_log_context().get("customer_id") or customer_id
        final_session_id = getattr(request.state, "session_id", None) or get_log_context().get("session_id") or session_id

        err_extra = {
            "method": request.method,
            "endpoint": request.url.path,
            "latency_ms": latency_ms,
            "session_id": final_session_id or "",
            "error": str(exc)
        }
        if final_customer_id:
            err_extra["customer_id"] = str(final_customer_id)

        logger.error(
            f"Unhandled exception during {request.method} {request.url.path}: {str(exc)}",
            extra=err_extra,
            exc_info=True
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error occurred."}
        )


# 2. Sliding Window Rate Limiting Middleware
@app.middleware("http")
async def rate_limiting_middleware(request: Request, call_next):
    # Exclude health checks, documentation, UI static files, and root/admin endpoints from rate limiting
    exempt_paths = ["/health", "/metrics", "/docs", "/openapi.json", "/redoc", "/", "/admin"]
    if request.url.path in exempt_paths or request.url.path.startswith("/static"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    session_id = request.query_params.get("session_id", "")
    key = f"{client_ip}:{session_id}" if session_id else client_ip

    # Rate limit check (configurable via RATE_LIMIT_PER_MINUTE, default 60 req/min)
    rate_limit_max = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    allowed, retry_after = limiter.is_allowed(key, max_requests=rate_limit_max, window_seconds=60)
    if not allowed:
        logger.warning(
            f"Rate limit exceeded for key {key} on {request.url.path}",
            extra={"action": "rate_limit_exceeded", "key": key, "retry_after": retry_after}
        )
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded. Please retry after {retry_after} seconds."},
            headers={"Retry-After": str(retry_after)}
        )

    return await call_next(request)


# Routers
app.include_router(onboarding.router)
app.include_router(escalation.router)

# Frontend Static Files & SPA Routing
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
index_file = os.path.join(frontend_dir, "index.html")

if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

# Uploaded Documents Endpoint & Static Mount (for Human Review & Preview)
import urllib.parse
import mimetypes
from fastapi.responses import HTMLResponse

uploads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(uploads_dir, exist_ok=True)

@app.get("/uploads/{file_path:path}")
async def serve_uploaded_document(file_path: str):
    """
    Serve uploaded document for preview/inspection with inline headers.
    Decodes URL encoding (spaces, special chars) and provides friendly preview fallback if file is missing.
    """
    decoded_path = urllib.parse.unquote(file_path)
    # Check exact decoded path or original path
    candidate_paths = [
        os.path.join(uploads_dir, decoded_path),
        os.path.join(uploads_dir, file_path),
        os.path.join(uploads_dir, os.path.basename(decoded_path)),
        os.path.join(uploads_dir, os.path.basename(file_path))
    ]
    
    target_file = None
    for cp in candidate_paths:
        if os.path.isfile(cp):
            target_file = cp
            break

    if target_file:
        mime_type, _ = mimetypes.guess_type(target_file)
        if not mime_type:
            if target_file.lower().endswith(".pdf"):
                mime_type = "application/pdf"
            elif target_file.lower().endswith((".png", ".jpg", ".jpeg")):
                mime_type = f"image/{target_file.split('.')[-1].lower()}"
            else:
                mime_type = "application/octet-stream"

        return FileResponse(
            path=target_file,
            media_type=mime_type,
            headers={
                "Content-Disposition": f"inline; filename=\"{os.path.basename(target_file)}\"",
                "Cache-Control": "no-cache"
            }
        )

    # Friendly HTML preview card when file is missing
    clean_name = os.path.basename(decoded_path)
    fallback_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{
            margin: 0;
            padding: 24px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #0f172a;
            color: #e2e8f0;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 220px;
        }}
        .card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 20px 24px;
            max-width: 480px;
            text-align: center;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
        }}
        .icon {{ font-size: 32px; margin-bottom: 8px; }}
        .title {{ font-size: 14px; font-weight: 700; color: #f8fafc; margin-bottom: 6px; }}
        .badge {{
            display: inline-block;
            background: #312e81;
            color: #c7d2fe;
            border: 1px solid #4338ca;
            padding: 2px 10px;
            border-radius: 9999px;
            font-size: 11px;
            font-family: monospace;
            margin-bottom: 10px;
        }}
        .desc {{ font-size: 12px; color: #94a3b8; line-height: 1.5; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">📄</div>
        <div class="title">Document Verification Summary</div>
        <div class="badge">{clean_name}</div>
        <div class="desc">
            This document was analyzed in-memory by the AI verification engine.<br>
            Please review the failure details and recommended action above to make your resolution decision.
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=fallback_html, status_code=200)


@app.get("/")
async def root(request: Request):
    accept_header = request.headers.get("accept", "")
    if "application/json" in accept_header and "text/html" not in accept_header:
        return {
            "service": "AI Customer Onboarding Agent API",
            "version": "1.0.0",
            "status": "operational",
            "docs_url": "/docs"
        }
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {
        "service": "AI Customer Onboarding Agent API",
        "version": "1.0.0",
        "status": "operational",
        "docs_url": "/docs"
    }


@app.get("/admin")
async def admin_portal(request: Request):
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {
        "service": "AI Customer Onboarding Operations Dashboard",
        "status": "operational"
    }


@app.get("/health")
async def health_check():
    """
    Deep Health Check:
    Verifies database connectivity, Groq API key presence, server uptime, and active sessions.
    """
    db_status = "unhealthy"
    db_ping_ms = None
    groq_status = "healthy" if os.getenv("GROQ_API_KEY") else "missing_key"
    active_sessions = 0

    # 1. Database Ping
    try:
        t0 = time.time()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1;"))
        db_ping_ms = round((time.time() - t0) * 1000, 2)
        db_status = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}", extra={"action": "health_check_db_fail"})
        db_status = f"unhealthy: {str(e)}"

    # 2. Active Sessions Count
    try:
        db = SessionLocal()
        active_sessions = db.query(Customer).filter(
            Customer.status.in_(["onboarding_started", "onboarding_resumed"])
        ).count()
        db.close()
    except Exception:
        pass

    # 3. Uptime
    start_time = getattr(app.state, "start_time", time.time())
    uptime_seconds = int(time.time() - start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    overall_status = "healthy" if (db_status == "healthy" and groq_status == "healthy") else "degraded"

    return {
        "status": overall_status,
        "uptime_seconds": uptime_seconds,
        "uptime": uptime_str,
        "database": {
            "status": db_status,
            "ping_latency_ms": db_ping_ms
        },
        "llm_service": {
            "provider": "Groq",
            "model": "qwen/qwen3.8-27b",
            "status": groq_status
        },
        "active_onboarding_sessions": active_sessions
    }


@app.get("/metrics")
async def system_metrics():
    """
    High-level operational metrics for observability.
    """
    try:
        db = SessionLocal()
        total_customers = db.query(Customer).count()
        completed = db.query(Customer).filter(Customer.status.in_(["active", "complete", "completed"])).count()
        escalated = db.query(Customer).filter(Customer.status.in_(["escalated", "blocked"])).count()
        in_progress = total_customers - completed - escalated
        db.close()
    except Exception:
        total_customers = completed = escalated = in_progress = 0

    return {
        "metrics": {
            "total_customers": total_customers,
            "in_progress_sessions": max(0, in_progress),
            "completed_sessions": completed,
            "escalated_sessions": escalated,
            "rate_limiter_active_keys": len(limiter.requests)
        }
    }


if __name__ == "__main__":
    import sys
    import asyncio
    import uvicorn
    from uvicorn.config import Config
    from uvicorn.server import Server

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def _run_server():
        port = int(os.getenv("PORT", "8000"))
        config = Config(app, host="0.0.0.0", port=port, log_level="info")
        server = Server(config)
        await server.serve()

    asyncio.run(_run_server())