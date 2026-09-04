print("[LOAD] backend/agent/state.py is being imported")
from typing import TypedDict, Optional, Dict, Any, List

class AgentState(TypedDict, total=False):
    # ===== Customer Info =====
    customer_id: Optional[str]
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    company_name: Optional[str]
    customer_type: Optional[str]  # "individual", "enterprise", "startup"
    
    # ===== Session & Flow =====
    session_id: str
    current_step: str  # greeting, collect_info, validate_info, collect_docs, validate_docs, api_trigger, escalation, completion, complete, error
    message: str  # Latest user message
    
    # ===== Collected Data =====
    collected_info: Dict[str, Any]  # name, email, phone, etc.
    pending_items: List[str]  # ["email", "pan_card", etc.]
    missing_info: List[str]   # Fields still missing
    documents_status: Dict[str, str]  # {"pan_card": "pending/verified/rejected"}
    
    # ===== Conversation =====
    messages: List[Dict[str, str]]  # Chat history [{"role": "user/assistant", "content": "..."}]
    
    # ===== Tasks =====
    tasks: List[Dict[str, Any]]  # Task results from APIs
    
    # ===== Escalation =====
    needs_escalation: bool
    escalation_reason: Optional[str]
    human_context: Optional[str]  # Context for human agent
    
    # ===== Metadata =====
    errors: List[str]
    retry_count: int
    task_status: str  # "pending", "in_progress", "completed", "failed"
    escalation_required: bool  # Alternative flag for compatibility
    response: str  # Latest assistant response


def initialize_state(
    customer_id: Optional[str] = None,
    session_id: str = "",
    message: str = "",
    customer_type: Optional[str] = None
) -> AgentState:
    """
    Initialize a new agent state with default values.
    Pre-populates customer_type if already chosen by the user in UI.
    """
    ctype = customer_type.lower().strip() if customer_type and customer_type.lower().strip() in ["individual", "startup", "enterprise"] else None
    collected_info = {}
    pending_items = ["name", "email", "phone", "customer_type"]
    if ctype:
        collected_info["customer_type"] = ctype
        pending_items = ["name", "email", "phone"]

    return AgentState(
        # Customer Info
        customer_id=customer_id,
        name=None,
        email=None,
        phone=None,
        company_name=None,
        customer_type=ctype,
        
        # Session & Flow
        session_id=session_id,
        current_step="greeting",
        message=message,
        
        # Collected Data
        collected_info=collected_info,
        pending_items=pending_items,
        missing_info=pending_items,
        documents_status={},
        
        # Conversation
        messages=[],
        
        # Tasks
        tasks=[],
        
        # Escalation
        needs_escalation=False,
        escalation_reason=None,
        human_context=None,
        
        # Metadata
        errors=[],
        retry_count=0,
        task_status="pending",
        escalation_required=False,
        response=""
    )


def get_initial_state(session_id: str) -> AgentState:
    """
    Convenience function to get initial state with session_id.
    """
    return initialize_state(session_id=session_id)