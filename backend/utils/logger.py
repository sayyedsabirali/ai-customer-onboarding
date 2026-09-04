import contextvars
import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional

# Context variables for async context propagation across request lifecycles
ctx_session_id = contextvars.ContextVar("ctx_session_id", default=None)
ctx_customer_id = contextvars.ContextVar("ctx_customer_id", default=None)


def set_log_context(session_id: Optional[str] = None, customer_id: Optional[str] = None) -> None:
    """Set correlation identifiers in the current async context."""
    if session_id is not None:
        ctx_session_id.set(str(session_id) if session_id else None)
    if customer_id is not None:
        ctx_customer_id.set(str(customer_id) if customer_id else None)


def clear_log_context() -> None:
    """Clear context variables."""
    ctx_session_id.set(None)
    ctx_customer_id.set(None)


def get_log_context() -> Dict[str, Optional[str]]:
    """Retrieve current correlation identifiers from context."""
    return {
        "session_id": ctx_session_id.get(),
        "customer_id": ctx_customer_id.get()
    }


class JSONFormatter(logging.Formatter):
    """
    Formatter that outputs JSON strings with standard observability fields.
    Automatically includes context variables (session_id, customer_id) if available.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Resolve session_id: check record attribute first, then contextvar
        session_id = getattr(record, "session_id", None) or ctx_session_id.get()
        if session_id:
            log_data["session_id"] = str(session_id)

        # Resolve customer_id: check record attribute first, then contextvar
        customer_id = getattr(record, "customer_id", None) or ctx_customer_id.get()
        if customer_id:
            log_data["customer_id"] = str(customer_id)

        # Include custom extra fields if provided
        for key in ["endpoint", "method", "status_code", "latency_ms", "action", "error"]:
            if hasattr(record, key):
                log_data[key] = getattr(record, key)

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_logging(level: int = logging.INFO) -> None:
    """Configures root logger with JSON formatting."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers if already configured
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(JSONFormatter())


def get_logger(name: str) -> logging.Logger:
    """Gets a logger configured with structured JSON format."""
    return logging.getLogger(name)
