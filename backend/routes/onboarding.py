print("[LOAD] backend/routes/onboarding.py is being imported")
import sys
import copy
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from uuid import UUID, uuid4
from langgraph.types import Command

from pydantic import BaseModel
from database.connection import SessionLocal
from database.models import OnboardingState, Customer
from agent.state import initialize_state
from agent.tools import (
    validate_document_tool,
    get_onboarding_summary_tool,
    escalate_tool,
    evaluate_sla_status,
    generate_follow_up_llm
)
from agent.config import is_valid_document_type, normalize_document_type, DOCUMENT_DISPLAY_NAMES, get_display_name
from utils.logger import set_log_context

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class BatchFollowUpRequest(BaseModel):
    session_ids: Optional[List[str]] = None
    customer_ids: Optional[List[str]] = None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def extract_response_and_step(result: dict):
    """
    Shared helper: pulls the correct response text and current_step
    whether the graph completed normally or paused on an interrupt().
    """
    response_text = result.get("response", "")
    current_step_val = result.get("current_step")

    if "__interrupt__" in result and result["__interrupt__"]:
        interrupt_payload = result["__interrupt__"][0].value
        response_text = interrupt_payload.get("message", response_text)
        current_step_val = interrupt_payload.get("current_step", current_step_val)

    return response_text, current_step_val


@router.post("/start")
async def start_onboarding(
    request: Request,
    customer_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        print("=" * 80, file=sys.stderr, flush=True)
        print(f"✅ /start ENDPOINT CALLED (customer_type: {customer_type})", file=sys.stderr, flush=True)
        print("=" * 80, file=sys.stderr, flush=True)

        graph = request.app.state.graph
        session_id = str(uuid4())
        state = initialize_state(customer_id=None, session_id=session_id, message="", customer_type=customer_type)
        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": 50
        }

        print(f"Graph: {type(graph).__name__}", file=sys.stderr, flush=True)
        print(f"State keys: {list(state.keys())}", file=sys.stderr, flush=True)

        try:
            print("Invoking graph...", file=sys.stderr, flush=True)
            result = await graph.ainvoke(state, config=config)

            response_text, current_step_val = extract_response_and_step(result)
            print(f"Response: {response_text}", file=sys.stderr, flush=True)
            print(f"Current step: {current_step_val}", file=sys.stderr, flush=True)

            cust_id = result.get("customer_id")
            request.state.session_id = session_id
            if cust_id:
                request.state.customer_id = str(cust_id)
                set_log_context(session_id=session_id, customer_id=str(cust_id))

            return {
                "success": True,
                "session_id": session_id,
                "customer_id": cust_id,
                "current_step": current_step_val,
                "customer_type": None,
                "sla_hours": None,
                "response": response_text
            }
        except Exception as e:
            print(f"ainvoke error: {str(e)}", file=sys.stderr, flush=True)
            cust_id = state.get("customer_id")
            request.state.session_id = session_id
            if cust_id:
                request.state.customer_id = str(cust_id)
                set_log_context(session_id=session_id, customer_id=str(cust_id))

            return {
                "success": True,
                "session_id": session_id,
                "customer_id": cust_id,
                "current_step": state.get("current_step"),
                "customer_type": None,
                "sla_hours": None,
                "response": state.get("response", "")
            }
    except Exception as e:
        print(f"❌ ENDPOINT ERROR: {str(e)}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"success": False, "error": str(e)}


@router.post("/resume")
async def resume_onboarding(
    request: Request,
    email: Optional[str] = None,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Resume onboarding using email or session_id.
    - If email is provided, finds the customer's active/latest onboarding session.
    - session_id is preserved internally as the thread identifier.
    - Fully restores: customer details, account tier, SLA, current step, document statuses,
      chat history, escalation state, and pending items.
    """
    state_record = None
    resolved_session_id = session_id.strip() if session_id else None

    # Support JSON request body if query params are not provided
    if not email and not session_id:
        try:
            body_data = await request.json()
            if isinstance(body_data, dict):
                email = body_data.get("email") or email
                session_id = body_data.get("session_id") or session_id
                resolved_session_id = session_id.strip() if session_id else None
        except Exception:
            pass

    # Find by email if provided
    if email and email.strip():
        clean_email = email.strip().lower()
        customer = db.query(Customer).filter(
            Customer.email.ilike(clean_email)
        ).order_by(Customer.created_at.desc()).first()

        if customer:
            state_record = db.query(OnboardingState).filter(
                OnboardingState.customer_id == customer.id
            ).order_by(OnboardingState.created_at.desc()).first()
            if state_record and state_record.session_id:
                resolved_session_id = state_record.session_id
        else:
            # Also check within collected_info JSONB for in-flight sessions before customer table insertion
            all_states = db.query(OnboardingState).order_by(OnboardingState.created_at.desc()).limit(100).all()
            for st in all_states:
                st_info = st.collected_info or {}
                if (st_info.get("email") or "").strip().lower() == clean_email:
                    state_record = st
                    resolved_session_id = st.session_id
                    break

        if not resolved_session_id:
            raise HTTPException(
                status_code=404,
                detail=f"No onboarding session found for email '{email}'. Please check your email address or start a new onboarding session."
            )

    # Fallback / explicit lookup by session_id
    if not state_record and resolved_session_id:
        state_record = db.query(OnboardingState).filter(
            OnboardingState.session_id == resolved_session_id
        ).order_by(OnboardingState.created_at.desc()).first()

    if not state_record:
        raise HTTPException(status_code=404, detail="Session not found")

    session_id = resolved_session_id or state_record.session_id
    request.state.session_id = session_id
    if state_record.customer_id:
        request.state.customer_id = str(state_record.customer_id)
        set_log_context(session_id=session_id, customer_id=str(state_record.customer_id))

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": session_id}}

    try:
        current_state = await graph.aget_state(config)
        state_values = current_state.values if current_state and current_state.values else {}

        cust = None
        if state_record.customer_id:
            cust = db.query(Customer).filter(Customer.id == state_record.customer_id).first()

        c_type = cust.customer_type if cust else (state_values.get("customer_type") or (state_record.collected_info or {}).get("customer_type"))
        sla_hours = cust.sla_hours if (cust and cust.sla_hours) else ((72 if c_type == "enterprise" else 48 if c_type == "startup" else 24) if c_type else None)
        hist_messages = list(state_values.get("messages") or [])
        if not hist_messages and state_record:
            hist_messages = list((state_record.collected_info or {}).get("messages") or [])

        # Deduplicate consecutive duplicate messages
        cleaned_hist = []
        for m in hist_messages:
            c_text = (m.get("content") or m.get("text") or "").strip()
            c_role = m.get("role", "assistant")
            if not c_text:
                continue
            if not cleaned_hist or cleaned_hist[-1].get("role") != c_role or cleaned_hist[-1].get("content") != c_text:
                cleaned_hist.append({"role": c_role, "content": c_text})
        hist_messages = cleaned_hist

        if hist_messages and state_record:
            c_info = copy.deepcopy(state_record.collected_info or {})
            if not c_info.get("messages") or len(c_info.get("messages", [])) < len(hist_messages):
                c_info["messages"] = hist_messages
                state_record.collected_info = c_info
                flag_modified(state_record, "collected_info")
                db.commit()

        # Check escalation state
        is_escalated = False
        escalation_reason = None
        if state_record.customer_id:
            from database.models import Escalation
            esc_rec = db.query(Escalation).filter(
                Escalation.customer_id == state_record.customer_id,
                Escalation.status == "pending"
            ).order_by(Escalation.created_at.desc()).first()
            if esc_rec:
                is_escalated = True
                escalation_reason = esc_rec.reason

        if not is_escalated and state_record.current_step in ["escalated", "escalation"]:
            is_escalated = True
            escalation_reason = (state_record.collected_info or {}).get("escalation_reason", "Case escalated to human support team")

        # Check rejection state
        is_rejected = (cust and cust.status == "rejected") or (state_record and state_record.current_step == "rejected") or ((state_record.collected_info or {}).get("customer_status") == "rejected")
        rejection_notes = None
        if is_rejected:
            rejection_notes = (state_record.collected_info or {}).get("rejection_notes")
            if not rejection_notes and state_record.customer_id:
                try:
                    from database.models import Escalation
                    esc_rej = db.query(Escalation).filter(
                        Escalation.customer_id == state_record.customer_id,
                        Escalation.status == "rejected"
                    ).order_by(Escalation.resolved_at.desc()).first()
                    if esc_rej:
                        rejection_notes = esc_rej.resolution_notes
                except Exception:
                    pass

        # Base payload for resuming session
        base_payload = {
            "success": True,
            "session_id": session_id,
            "customer_id": str(state_record.customer_id) if state_record.customer_id else None,
            "customer_name": cust.name if cust else (state_record.collected_info or {}).get("name"),
            "customer_email": cust.email if cust else (state_record.collected_info or {}).get("email"),
            "customer_type": c_type,
            "customer_status": cust.status if cust else ("rejected" if is_rejected else "onboarding_started"),
            "sla_hours": sla_hours,
            "pending_items": [] if is_rejected else (state_record.pending_items or []),
            "documents_status": state_record.documents_status or {},
            "collected_info": state_record.collected_info or {},
            "is_escalated": False if is_rejected else is_escalated,
            "is_rejected": is_rejected,
            "rejection_notes": rejection_notes,
            "escalation_reason": escalation_reason,
            "messages": hist_messages
        }

        # If permanently rejected, return immediately with rejected state
        if is_rejected:
            return {
                **base_payload,
                "current_step": "rejected",
                "response": "❌ Your onboarding application has been reviewed and rejected by our verification team."
            }

        # If graph is already at END (completed)
        if current_state and not current_state.next:
            return {
                **base_payload,
                "current_step": state_record.current_step or "complete",
                "response": state_values.get("response", "🎉 Onboarding is already completed!"),
            }

        # If paused on an interrupt, return the pending question/instruction
        if current_state and current_state.tasks and any(t.interrupts for t in current_state.tasks):
            interrupt_val = current_state.tasks[0].interrupts[0].value
            int_doc = interrupt_val.get("document_type") if isinstance(interrupt_val, dict) else None
            doc_st = state_record.documents_status or {}

            # If the interrupt is for a document that is ALREADY verified, advance the graph!
            if int_doc and doc_st.get(int_doc) == "verified":
                try:
                    resume_payload = {
                        "action": "upload_document",
                        "document_type": int_doc,
                        "status": "uploaded",
                        "verified": True
                    }
                    result = await graph.ainvoke(Command(resume=resume_payload), config=config)
                    response_text, current_step_val = extract_response_and_step(result)
                    return {
                        **base_payload,
                        "current_step": current_step_val,
                        "response": response_text,
                        "messages": result.get("messages", hist_messages),
                        "pending_items": [d for d in (result.get("pending_items") or base_payload["pending_items"]) if doc_st.get(d) != "verified"],
                        "documents_status": result.get("documents_status") or base_payload["documents_status"]
                    }
                except Exception as ex:
                    print(f"[WARN] Error auto-resuming obsolete interrupt: {ex}", file=sys.stderr, flush=True)

            msg = interrupt_val.get("message") if isinstance(interrupt_val, dict) else str(interrupt_val)
            step = interrupt_val.get("current_step", state_record.current_step) if isinstance(interrupt_val, dict) else state_record.current_step
            if msg and (not hist_messages or hist_messages[-1].get("content") != msg):
                hist_messages.append({"role": "assistant", "content": msg})
                base_payload["messages"] = hist_messages
            return {
                **base_payload,
                "current_step": step,
                "response": msg
            }

        if not state_values:
            state = initialize_state(
                customer_id=str(state_record.customer_id) if state_record.customer_id else None,
                session_id=session_id,
                message="",
                customer_type=c_type
            )
        else:
            state = state_values

        result = await graph.ainvoke(state, config=config)
        response_text, current_step_val = extract_response_and_step(result)

        return {
            **base_payload,
            "customer_id": result.get("customer_id") or base_payload["customer_id"],
            "customer_type": result.get("customer_type") or c_type,
            "current_step": current_step_val,
            "response": response_text,
            "messages": result.get("messages", hist_messages),
            "pending_items": result.get("pending_items") or base_payload["pending_items"],
            "documents_status": result.get("documents_status") or base_payload["documents_status"]
        }
    except Exception as e:
        print(f"[WARN] /resume exception: {str(e)}", file=sys.stderr, flush=True)
        cust = db.query(Customer).filter(Customer.id == state_record.customer_id).first() if state_record.customer_id else None
        c_type = cust.customer_type if cust else (state_record.collected_info or {}).get("customer_type", "individual")
        sla_h = cust.sla_hours if (cust and cust.sla_hours) else (72 if c_type == "enterprise" else 48 if c_type == "startup" else 24)
        db_msgs = list((state_record.collected_info or {}).get("messages") or [])
        return {
            "success": True,
            "session_id": session_id,
            "customer_id": str(state_record.customer_id) if state_record.customer_id else None,
            "customer_name": cust.name if cust else (state_record.collected_info or {}).get("name"),
            "customer_email": cust.email if cust else (state_record.collected_info or {}).get("email"),
            "customer_type": c_type,
            "sla_hours": sla_h,
            "current_step": state_record.current_step,
            "pending_items": state_record.pending_items or [],
            "documents_status": state_record.documents_status or {},
            "collected_info": state_record.collected_info or {},
            "is_escalated": state_record.current_step in ["escalated", "escalation"],
            "response": f"Session resumed. Current step: {state_record.current_step}. Pending items: {state_record.pending_items or []}",
            "messages": db_msgs
        }


@router.post("/chat")
async def chat(
    request: Request,
    session_id: str,
    message: str,
    db: Session = Depends(get_db)
):
    """
    Send a chat message using session_id.
    Uses Command(resume=message) to resume from the current interrupt.
    """
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": session_id}}

    # Check if application has been permanently rejected
    state_rec = db.query(OnboardingState).filter(OnboardingState.session_id == session_id).order_by(OnboardingState.created_at.desc()).first()
    if state_rec:
        cust = db.query(Customer).filter(Customer.id == state_rec.customer_id).first() if state_rec.customer_id else None
        if (cust and cust.status == "rejected") or state_rec.current_step == "rejected" or ((state_rec.collected_info or {}).get("customer_status") == "rejected"):
            raise HTTPException(
                status_code=403,
                detail="Your onboarding application has been rejected. Chat is disabled."
            )

    result = await graph.ainvoke(
        Command(resume=message),
        config=config
    )

    response_text, current_step_val = extract_response_and_step(result)

    res_msgs = result.get("messages", [])
    cleaned_res_msgs = []
    for m in res_msgs:
        c_text = (m.get("content") or m.get("text") or "").strip()
        c_role = m.get("role", "assistant")
        if not c_text:
            continue
        if not cleaned_res_msgs or cleaned_res_msgs[-1].get("role") != c_role or cleaned_res_msgs[-1].get("content") != c_text:
            cleaned_res_msgs.append({"role": c_role, "content": c_text})

    state_rec = db.query(OnboardingState).filter(OnboardingState.session_id == session_id).order_by(OnboardingState.created_at.desc()).first()
    if state_rec:
        state_rec.last_interaction_at = datetime.now()
        if cleaned_res_msgs:
            c_info = copy.deepcopy(state_rec.collected_info or {})
            c_info["messages"] = cleaned_res_msgs
            state_rec.collected_info = c_info
            flag_modified(state_rec, "collected_info")
        db.commit()

    # Propagate customer_id and session_id for structured request logging
    resolved_customer_id = result.get("customer_id")
    if not resolved_customer_id and state_rec and state_rec.customer_id:
        resolved_customer_id = str(state_rec.customer_id)

    request.state.session_id = session_id
    if resolved_customer_id:
        request.state.customer_id = str(resolved_customer_id)
        set_log_context(session_id=session_id, customer_id=str(resolved_customer_id))

    c_type = result.get("customer_type") or result.get("collected_info", {}).get("customer_type")
    if not c_type and state_rec and state_rec.customer_id:
        c_cust = db.query(Customer).filter(Customer.id == state_rec.customer_id).first()
        if c_cust:
            c_type = c_cust.customer_type
    sla_h = (72 if c_type == "enterprise" else 48 if c_type == "startup" else 24) if c_type else None

    return {
        "success": True,
        "session_id": session_id,
        "customer_id": resolved_customer_id,
        "response": response_text,
        "current_step": current_step_val,
        "customer_type": c_type,
        "sla_hours": sla_h,
        "collected_info": result.get("collected_info", {}),
        "pending_items": result.get("pending_items", []),
        "documents_status": result.get("documents_status", {}),
        "messages": cleaned_res_msgs
    }


@router.post("/document")
async def upload_document(
    request: Request,
    session_id: str,
    document_type: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload and validate an onboarding document.
    """
    # Normalize document_type
    normalized_type = normalize_document_type(document_type)
    if not normalized_type:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document_type '{document_type}'. Allowed types or names: {list(DOCUMENT_DISPLAY_NAMES.values())}"
        )
    document_type = normalized_type

    # Get the onboarding state record
    state_record = db.query(OnboardingState).filter(
        OnboardingState.session_id == session_id
    ).order_by(OnboardingState.created_at.desc()).first()

    if not state_record:
        # Fallback to LangGraph checkpointer state
        graph = request.app.state.graph
        try:
            curr_state = await graph.aget_state({"configurable": {"thread_id": session_id}})
            if curr_state and curr_state.values:
                cid_str = curr_state.values.get("customer_id")
                if cid_str:
                    state_record = OnboardingState(
                        customer_id=UUID(cid_str),
                        session_id=session_id,
                        current_step=curr_state.values.get("current_step", "collect_docs"),
                        collected_info=curr_state.values.get("collected_info", {}),
                        pending_items=curr_state.values.get("pending_items", []),
                        documents_status=curr_state.values.get("documents_status", {})
                    )
                    db.add(state_record)
                    db.commit()
                    db.refresh(state_record)
        except Exception as e:
            print(f"Error checking checkpointer in upload_document: {e}", file=sys.stderr)

    if not state_record:
        raise HTTPException(status_code=404, detail="Session not found")

    customer_id = state_record.customer_id
    if not customer_id:
        raise HTTPException(status_code=400, detail="Customer not created yet. Please complete information first.")

    # Check if application has been permanently rejected
    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if (cust and cust.status == "rejected") or state_record.current_step == "rejected" or ((state_record.collected_info or {}).get("customer_status") == "rejected"):
        raise HTTPException(
            status_code=403,
            detail="Your onboarding application has been rejected. Document uploads are disabled."
        )

    request.state.session_id = session_id
    request.state.customer_id = str(customer_id)
    set_log_context(session_id=session_id, customer_id=str(customer_id))

    # ---- Read file bytes for deep content verification ----
    file_bytes = await file.read()
    file_size = len(file_bytes) if file_bytes else (file.size or 0)

    # Save physical file to uploads/ for human preview and review
    uploads_dir = Path(__file__).resolve().parent.parent.parent / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    clean_filename = f"{session_id[:8]}_{document_type}_{file.filename.replace(' ', '_')}"
    saved_path = uploads_dir / clean_filename
    with open(saved_path, "wb") as f_out:
        f_out.write(file_bytes)

    file_url = f"/uploads/{clean_filename}"
    doc_data = {
        "document_type": document_type,
        "file_name": file.filename,
        "file_size": file_size,
        "file_url": file_url,
        "file_bytes": file_bytes
    }

    doc_result = validate_document_tool(db, customer_id, doc_data)
    if not doc_result["success"]:
        # Track failed attempts for this document type
        info = copy.deepcopy(state_record.collected_info or {})
        doc_attempts = info.get("doc_attempts", {})
        attempts = doc_attempts.get(document_type, 0) + 1
        doc_attempts[document_type] = attempts
        info["doc_attempts"] = doc_attempts
        state_record.collected_info = info
        flag_modified(state_record, "collected_info")
        db.commit()

        err_detail = doc_result["error"]
        if attempts >= 3:
            # Update state record step & documents_status
            state_record.current_step = "escalated"
            doc_st = copy.deepcopy(state_record.documents_status or {})
            doc_st[document_type] = "escalated"
            state_record.documents_status = doc_st
            flag_modified(state_record, "documents_status")

            # Trigger automatic human escalation!
            esc_res = escalate_tool(
                db=db,
                customer_id=customer_id,
                reason=f"Verification failed 3 times for {document_type}: {err_detail}",
                context={
                    "document_type": document_type,
                    "attempts": attempts,
                    "last_file": file.filename,
                    "file_name": file.filename,
                    "file_url": file_url,
                    "error": err_detail
                },
                recommended_action=f"Manually review customer {document_type} or request physical copy verification",
                session_id=session_id
            )
            db.commit()
            esc_id = esc_res.get("escalation_id", "")
            short_id = esc_id[:8] if esc_id else "ESC"
            raise HTTPException(
                status_code=400,
                detail=f"{err_detail}\n\n⚠️ Maximum 3 verification attempts reached. Your case has been escalated to our human support team (Ticket: #{short_id}). An agent will review your document shortly."
            )
        else:
            remaining = 3 - attempts
            raise HTTPException(
                status_code=400,
                detail=f"{err_detail} (Attempt {attempts}/3. {remaining} attempt{'s' if remaining != 1 else ''} remaining before human escalation)."
            )

    document_id = doc_result.get("document_id")

    # ---- Keep temporary verification state in application/session state (in-memory) ----
    # DO NOT commit intermediate pending state to DB to avoid redundant DB writes
    docs_status = copy.deepcopy(state_record.documents_status or {})
    docs_status[document_type] = "verified"

    # ---- Resume LangGraph ----
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": session_id}}

    resume_value = {
        "document_type": document_type,
        "status": "uploaded",
        "file_url": file_url,
        "verified": True
    }

    try:
        result = await graph.ainvoke(
            Command(resume=resume_value),
            config=config
        )

        response_text, current_step_val = extract_response_and_step(result)

        res_msgs = result.get("messages", [])
        cleaned_res_msgs = []
        for m in res_msgs:
            c_text = (m.get("content") or m.get("text") or "").strip()
            c_role = m.get("role", "assistant")
            if not c_text:
                continue
            if not cleaned_res_msgs or cleaned_res_msgs[-1].get("role") != c_role or cleaned_res_msgs[-1].get("content") != c_text:
                cleaned_res_msgs.append({"role": c_role, "content": c_text})

        # ---- Persist the final VERIFIED state ONCE (consolidated single DB commit) ----
        final_docs_status = copy.deepcopy(result.get("documents_status") or docs_status)
        final_docs_status[document_type] = "verified"
        state_record.documents_status = final_docs_status
        state_record.current_step = current_step_val
        state_record.pending_items = result.get("pending_items", [])
        state_record.last_interaction_at = datetime.now()

        if cleaned_res_msgs:
            c_info = copy.deepcopy(state_record.collected_info or {})
            c_info["messages"] = cleaned_res_msgs
            state_record.collected_info = c_info
            flag_modified(state_record, "collected_info")

        flag_modified(state_record, "documents_status")
        flag_modified(state_record, "pending_items")
        db.commit()

        return {
            "success": True,
            "document_id": document_id,  # ✅ Returns the actual ID
            "current_step": current_step_val,
            "response": response_text,
            "message": f"✅ {document_type} uploaded successfully. Onboarding resumed.",
            "messages": cleaned_res_msgs
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Resume failed: {str(e)}")

@router.get("/dashboard")
async def get_operational_dashboard(
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Operational Admin Dashboard with SLA Tracking & At-Risk Prioritization.
    Returns:
      - KPI metrics (total, active, completed, escalated, at-risk, breached, SLA compliance %)
      - Prioritized onboarding queue sorted by urgency (breached > at_risk > on_track)
    """
    customers = db.query(Customer).order_by(Customer.created_at.desc()).all()

    total_customers = len(customers)
    active_count = 0
    completed_count = 0
    escalated_count = 0
    at_risk_count = 0
    breached_count = 0
    sla_met_count = 0

    now = datetime.now()
    queue = []

    # Pre-fetch all latest states in a single query for maximum performance
    all_states = db.query(OnboardingState).order_by(OnboardingState.created_at.desc()).all()
    latest_state_by_customer = {}
    for st in all_states:
        if st.customer_id and st.customer_id not in latest_state_by_customer:
            latest_state_by_customer[st.customer_id] = st

    for cust in customers:
        sla_info = evaluate_sla_status(cust, current_time=now)
        sla_status = sla_info["sla_status"]

        is_completed = (cust.status in ["active", "complete", "completed"]) or (cust.completed_at is not None)
        is_escalated = (cust.status in ["escalated", "blocked"])

        if is_completed:
            completed_count += 1
            if sla_status == "met":
                sla_met_count += 1
            else:
                breached_count += 1
        elif is_escalated:
            escalated_count += 1
            if sla_status == "breached":
                breached_count += 1
            elif sla_status == "at_risk":
                at_risk_count += 1
        else:
            active_count += 1
            if sla_status == "breached":
                breached_count += 1
            elif sla_status == "at_risk":
                at_risk_count += 1

        # Use pre-indexed latest state
        state_record = latest_state_by_customer.get(cust.id)

        queue.append({
            "customer_id": str(cust.id),
            "session_id": state_record.session_id if state_record else None,
            "customer_name": cust.name,
            "email": cust.email,
            "customer_type": cust.customer_type,
            "customer_status": cust.status,
            "current_step": state_record.current_step if state_record else "not_started",
            "pending_items": state_record.pending_items if state_record else [],
            "sla_hours": sla_info["sla_hours"],
            "sla_deadline": sla_info["sla_deadline"],
            "remaining_hours": sla_info["remaining_hours"],
            "sla_percentage_used": sla_info["sla_percentage_used"],
            "sla_status": sla_info["sla_status"],
            "is_at_risk": sla_info["is_at_risk"],
            "urgency_score": sla_info["urgency_score"],
            "follow_up_count": state_record.follow_up_count if state_record else 0,
            "last_interaction_at": state_record.last_interaction_at.isoformat() if (state_record and state_record.last_interaction_at) else None,
            "created_at": cust.created_at.isoformat() if cust.created_at else None
        })

    # Sort prioritized queue by urgency_score descending (most critical first!)
    queue.sort(key=lambda x: x["urgency_score"], reverse=True)

    compliance_rate = f"{round((sla_met_count / completed_count * 100), 1)}%" if completed_count > 0 else "0.0%"

    return {
        "kpis": {
            "total_customers": total_customers,
            "active_onboarding": active_count,
            "completed_onboarding": completed_count,
            "escalated_onboarding": escalated_count,
            "at_risk_count": at_risk_count,
            "sla_breached_count": breached_count,
            "sla_compliance_rate": compliance_rate
        },
        "prioritized_queue": queue[:limit]
    }


@router.post("/follow-up")
async def trigger_batch_follow_up(
    request: Request,
    payload: Optional[BatchFollowUpRequest] = None,
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """
    Automated Proactive Follow-Up:
    - If session_ids/customer_ids are provided in the payload, targets specifically those selected customers.
    - Otherwise scans active onboarding sessions up to limit.
    - Generates personalized LLM reminders based on each customer's specific pending documents.
    - Updates follow-up count and interaction history.
    """
    selected_sids = None
    if payload and payload.session_ids:
        selected_sids = [s.strip() for s in payload.session_ids if s and s.strip()]
    elif payload and payload.customer_ids:
        resolved_sids = []
        for cid in payload.customer_ids:
            try:
                st_rec = db.query(OnboardingState).filter(OnboardingState.customer_id == UUID(cid)).order_by(OnboardingState.created_at.desc()).first()
                if st_rec and st_rec.session_id:
                    resolved_sids.append(st_rec.session_id)
            except Exception:
                pass
        if resolved_sids:
            selected_sids = resolved_sids
    else:
        try:
            body = await request.json()
            if isinstance(body, dict) and body.get("session_ids"):
                selected_sids = [s.strip() for s in body["session_ids"] if s and s.strip()]
        except Exception:
            pass

    states = []
    if selected_sids is not None:
        seen_sids = set()
        for sid in selected_sids:
            if sid in seen_sids:
                continue
            seen_sids.add(sid)
            st = db.query(OnboardingState).filter(
                OnboardingState.session_id == sid
            ).order_by(OnboardingState.created_at.desc()).first()
            if st:
                states.append(st)
    else:
        states = db.query(OnboardingState).join(Customer, OnboardingState.customer_id == Customer.id).filter(
            Customer.status.in_(["onboarding_started", "onboarding_resumed"]),
            OnboardingState.current_step.in_(["collect_info", "collect_docs"])
        ).order_by(OnboardingState.created_at.desc()).limit(limit).all()

    follow_up_results = []
    now = datetime.now()

    for st in states:
        cust = db.query(Customer).filter(Customer.id == st.customer_id).first() if st.customer_id else None
        if not cust:
            continue

        pending = [p for p in (st.pending_items or []) if (st.documents_status or {}).get(p) != "verified"]
        if not pending:
            continue

        # Skip already completed customers
        if cust.status in ["active", "complete", "completed", "verified"] or st.current_step in ["complete", "completed"]:
            continue

        sla_info = evaluate_sla_status(cust, current_time=now)
        sla_status = sla_info["sla_status"]
        rem_hours = sla_info["remaining_hours"]

        follow_up_msg = generate_follow_up_llm(
            customer_name=cust.name,
            customer_type=cust.customer_type,
            pending_items=pending,
            sla_status=sla_status,
            remaining_hours=rem_hours
        )

        st.follow_up_count = (st.follow_up_count or 0) + 1
        st.last_follow_up_at = now

        info = copy.deepcopy(st.collected_info or {})
        history = info.get("follow_ups", [])
        history.append({
            "timestamp": now.isoformat(),
            "sla_status": sla_status,
            "message": follow_up_msg
        })
        info["follow_ups"] = history
        st.collected_info = info
        flag_modified(st, "collected_info")

        follow_up_results.append({
            "session_id": st.session_id,
            "customer_id": str(cust.id),
            "customer_name": cust.name,
            "email": cust.email,
            "customer_type": cust.customer_type,
            "sla_status": sla_status,
            "remaining_hours": rem_hours,
            "pending_items": pending,
            "follow_up_count": st.follow_up_count,
            "follow_up_message": follow_up_msg
        })

    db.commit()

    return {
        "success": True,
        "total_follow_ups_sent": len(follow_up_results),
        "follow_ups": follow_up_results
    }


@router.post("/follow-up/{session_id}")
async def trigger_single_follow_up(
    session_id: str,
    db: Session = Depends(get_db)
):
    """
    Trigger a proactive AI follow-up reminder for a specific session.
    """
    st = db.query(OnboardingState).filter(
        OnboardingState.session_id == session_id
    ).order_by(OnboardingState.created_at.desc()).first()

    if not st:
        raise HTTPException(status_code=404, detail="Onboarding session not found")

    cust = db.query(Customer).filter(Customer.id == st.customer_id).first() if st.customer_id else None
    if not cust:
        raise HTTPException(status_code=400, detail="Customer not created yet for this session")

    now = datetime.now()
    pending = st.pending_items or []
    sla_info = evaluate_sla_status(cust, current_time=now)
    sla_status = sla_info["sla_status"]
    rem_hours = sla_info["remaining_hours"]

    # Follow-up should only be available for incomplete/stuck onboarding sessions with actual pending items
    is_completed = (
        cust.status in ["completed", "verified"]
        or st.current_step in ["complete", "completed", "verified"]
        or sla_status == "met"
        or len(pending) == 0
    )

    if is_completed:
        raise HTTPException(
            status_code=400,
            detail=f"Customer '{cust.name}' has already completed onboarding (SLA met). Follow-up is only available for incomplete sessions with pending items."
        )

    msg = generate_follow_up_llm(
        customer_name=cust.name,
        customer_type=cust.customer_type,
        pending_items=pending,
        sla_status=sla_status,
        remaining_hours=rem_hours
    )

    st.follow_up_count = (st.follow_up_count or 0) + 1
    st.last_follow_up_at = now

    info = copy.deepcopy(st.collected_info or {})
    history = info.get("follow_ups", [])
    history.append({
        "timestamp": now.isoformat(),
        "sla_status": sla_status,
        "message": msg
    })
    info["follow_ups"] = history
    st.collected_info = info
    flag_modified(st, "collected_info")
    db.commit()

    return {
        "success": True,
        "session_id": session_id,
        "customer_id": str(cust.id),
        "customer_name": cust.name,
        "sla_status": sla_status,
        "remaining_hours": rem_hours,
        "follow_up_count": st.follow_up_count,
        "follow_up_message": msg
    }


@router.get("/dashboard/{customer_id}")
async def get_dashboard(
    customer_id: UUID,
    request: Request,
    db: Session = Depends(get_db)
):
    """Get onboarding dashboard data for a customer."""
    request.state.customer_id = str(customer_id)
    set_log_context(customer_id=str(customer_id))
    result = get_onboarding_summary_tool(db, customer_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/state/{session_id}")
async def get_state_by_session(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """Get current onboarding state by session_id."""
    state_record = db.query(OnboardingState).filter(
        OnboardingState.session_id == session_id
    ).order_by(OnboardingState.created_at.desc()).first()

    graph = request.app.state.graph
    messages = []
    c_type_graph = None
    try:
        current_state = await graph.aget_state({"configurable": {"thread_id": session_id}})
        if current_state and current_state.values:
            val = current_state.values
            messages = list(val.get("messages") or [])
            c_type_graph = val.get("customer_type") or val.get("collected_info", {}).get("customer_type")
    except Exception:
        pass

    db_msgs = list((state_record.collected_info or {}).get("messages") or []) if (state_record and state_record.collected_info) else []
    if any("manually verified" in (m.get("content") or "").lower() for m in db_msgs) or len(db_msgs) > len(messages):
        messages = db_msgs
    elif not messages and db_msgs:
        messages = db_msgs

    cleaned_m = []
    for m in messages:
        c_text = (m.get("content") or m.get("text") or "").strip()
        c_role = m.get("role", "assistant")
        if not c_text:
            continue
        if not cleaned_m or cleaned_m[-1].get("role") != c_role or cleaned_m[-1].get("content") != c_text:
            cleaned_m.append({"role": c_role, "content": c_text})
    messages = cleaned_m

    if not state_record:
        if messages or c_type_graph is not None:
            c_type = c_type_graph
            sla_h = (72 if c_type == "enterprise" else 48 if c_type == "startup" else 24) if c_type else None
            return {
                "session_id": session_id,
                "customer_id": None,
                "customer_type": c_type,
                "sla_hours": sla_h,
                "current_step": "collect_info",
                "collected_info": {},
                "pending_items": [],
                "documents_status": {},
                "messages": messages
            }
        raise HTTPException(status_code=404, detail="State not found")

    request.state.session_id = session_id
    cust = None
    if state_record.customer_id:
        request.state.customer_id = str(state_record.customer_id)
        set_log_context(session_id=session_id, customer_id=str(state_record.customer_id))
        try:
            cust = db.query(Customer).filter(Customer.id == state_record.customer_id).first()
        except Exception as err:
            print(f"[WARN] Failed to query Customer in get_state_by_session: {err}", file=sys.stderr, flush=True)
            try:
                db.rollback()
            except Exception:
                pass

    c_type = cust.customer_type if cust else (c_type_graph or (state_record.collected_info or {}).get("customer_type"))
    sla_hours = cust.sla_hours if (cust and cust.sla_hours) else ((72 if c_type == "enterprise" else 48 if c_type == "startup" else 24) if c_type else None)

    # Check escalation state
    is_escalated = False
    escalation_reason = None
    if state_record.customer_id:
        try:
            from database.models import Escalation
            esc_rec = db.query(Escalation).filter(
                Escalation.customer_id == state_record.customer_id,
                Escalation.status == "pending"
            ).order_by(Escalation.created_at.desc()).first()
            if esc_rec:
                is_escalated = True
                escalation_reason = esc_rec.reason
        except Exception as err:
            print(f"[WARN] Failed to query Escalation in get_state_by_session: {err}", file=sys.stderr, flush=True)
            try:
                db.rollback()
            except Exception:
                pass

    # Check rejection state
    is_rejected = (cust and cust.status == "rejected") or (state_record.current_step == "rejected") or ((state_record.collected_info or {}).get("customer_status") == "rejected")
    rejection_notes = None
    if is_rejected:
        rejection_notes = (state_record.collected_info or {}).get("rejection_notes")
        if not rejection_notes and state_record.customer_id:
            try:
                from database.models import Escalation
                esc_rej = db.query(Escalation).filter(
                    Escalation.customer_id == state_record.customer_id,
                    Escalation.status == "rejected"
                ).order_by(Escalation.resolved_at.desc()).first()
                if esc_rej:
                    rejection_notes = esc_rej.resolution_notes
            except Exception:
                pass

    return {
        "session_id": session_id,
        "customer_id": str(state_record.customer_id) if state_record.customer_id else None,
        "customer_name": cust.name if cust else (state_record.collected_info or {}).get("name"),
        "customer_email": cust.email if cust else (state_record.collected_info or {}).get("email"),
        "customer_type": c_type,
        "customer_status": cust.status if cust else ("rejected" if is_rejected else "onboarding_started"),
        "sla_hours": sla_hours,
        "current_step": "rejected" if is_rejected else state_record.current_step,
        "collected_info": state_record.collected_info,
        "pending_items": [] if is_rejected else [d for d in (state_record.pending_items or []) if (state_record.documents_status or {}).get(d) != "verified"],
        "documents_status": state_record.documents_status,
        "is_escalated": False if is_rejected else is_escalated,
        "is_rejected": is_rejected,
        "rejection_notes": rejection_notes,
        "escalation_reason": escalation_reason,
        "messages": messages
    }


@router.get("/state/customer/{customer_id}")
async def get_state_by_customer(
    customer_id: UUID,
    request: Request,
    db: Session = Depends(get_db)
):
    """Get current onboarding state by customer_id."""
    request.state.customer_id = str(customer_id)
    set_log_context(customer_id=str(customer_id))
    state_record = db.query(OnboardingState).filter(
        OnboardingState.customer_id == customer_id
    ).order_by(OnboardingState.created_at.desc()).first()

    if not state_record:
        raise HTTPException(status_code=404, detail="State not found")

    return {
        "customer_id": str(customer_id),
        "session_id": state_record.session_id,
        "current_step": state_record.current_step,
        "collected_info": state_record.collected_info,
        "pending_items": state_record.pending_items,
        "documents_status": state_record.documents_status
    }