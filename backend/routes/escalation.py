print("[LOAD] backend/routes/escalation.py is being imported")
import sys
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from langgraph.types import Command

from database.connection import get_db
from database.models import Escalation, Customer, OnboardingState, Document
from agent.config import get_required_documents, get_display_name

router = APIRouter(prefix="/escalations", tags=["Human Escalation"])


# Human-readable display names for document types
DOC_DISPLAY_NAMES = {
    "pan_card": "PAN Card",
    "address_proof": "Address Proof (Aadhaar / Utility Bill)",
    "company_registration": "Company Registration Certificate",
    "gst_certificate": "GST Certificate",
}


def _doc_display(doc_type: str) -> str:
    return get_display_name(doc_type) or DOC_DISPLAY_NAMES.get(doc_type, doc_type.replace("_", " ").title() if doc_type else "Document")


class EscalationResolveRequest(BaseModel):
    action: str  # "approve", "request_reupload", "reject"
    resolution_notes: Optional[str] = None
    resolved_by: Optional[str] = "human_agent"
    # For request_reupload: custom message to send to the customer
    reupload_message: Optional[str] = None


@router.get("")
def list_escalations(
    status: Optional[str] = Query("all", description="Filter by status: pending, resolved, rejected, all"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    List escalations for human support dashboard.
    Shows customer info, failure reason, and AI-recommended action.
    """
    query = db.query(Escalation)
    if status and status.lower() != "all":
        query = query.filter(Escalation.status == status.lower())

    records = query.order_by(Escalation.created_at.desc()).limit(limit).all()

    results = []
    for esc in records:
        cust = esc.customer
        ctx = esc.context or {}
        doc_type = ctx.get("document_type")
        file_url = ctx.get("file_url")
        file_name = ctx.get("file_name") or ctx.get("last_file")

        # Fallback to Document table if needed
        if (not file_url or not doc_type) and esc.customer_id:
            last_doc = db.query(Document).filter(Document.customer_id == esc.customer_id).order_by(Document.uploaded_at.desc()).first()
            if last_doc:
                file_url = file_url or last_doc.file_url
                doc_type = doc_type or last_doc.document_type
                file_name = file_name or last_doc.file_name

        results.append({
            "id": str(esc.id),
            "escalation_id": str(esc.id),
            "customer_id": str(esc.customer_id) if esc.customer_id else "",
            "customer_name": cust.name if cust else "Unknown",
            "customer_email": cust.email if cust else "Unknown",
            "customer_type": cust.customer_type if cust else "unknown",
            "customer_status": cust.status if cust else "unknown",
            "session_id": esc.session_id,
            "document_type": doc_type,
            "file_url": file_url,
            "file_name": file_name,
            "reason": esc.reason,
            "recommended_action": esc.recommended_action,
            "status": esc.status,
            "context": ctx,
            "resolution_notes": esc.resolution_notes,
            "resolved_by": esc.resolved_by,
            "created_at": esc.created_at.isoformat() if esc.created_at else None,
            "resolved_at": esc.resolved_at.isoformat() if esc.resolved_at else None
        })

    return {
        "total": len(results),
        "status_filter": status,
        "escalations": results
    }


@router.get("/{escalation_id}")
def get_escalation_details(
    escalation_id: str,
    db: Session = Depends(get_db)
):
    """
    Get full details of a specific escalation with customer docs and history.
    """
    try:
        esc_uuid = UUID(escalation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid escalation UUID format")

    esc = db.query(Escalation).filter(Escalation.id == esc_uuid).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")

    cust = esc.customer
    docs = db.query(Document).filter(Document.customer_id == esc.customer_id).all()
    doc_list = [{
        "id": str(d.id),
        "type": d.document_type,
        "file_name": d.file_name,
        "status": d.status,
        "verification_notes": d.verification_notes
    } for d in docs]

    return {
        "escalation_id": str(esc.id),
        "customer": {
            "id": str(cust.id) if cust else None,
            "name": cust.name if cust else None,
            "email": cust.email if cust else None,
            "phone": cust.phone if cust else None,
            "customer_type": cust.customer_type if cust else None,
            "status": cust.status if cust else None
        },
        "session_id": esc.session_id,
        "reason": esc.reason,
        "recommended_action": esc.recommended_action,
        "status": esc.status,
        "context": esc.context,
        "documents": doc_list,
        "resolution_notes": esc.resolution_notes,
        "resolved_by": esc.resolved_by,
        "created_at": esc.created_at.isoformat() if esc.created_at else None,
        "resolved_at": esc.resolved_at.isoformat() if esc.resolved_at else None
    }


@router.post("/{escalation_id}/resolve")
async def resolve_escalation(
    escalation_id: str,
    request: Request,
    payload: Optional[EscalationResolveRequest] = None,
    resolution_notes: Optional[str] = Query(None),
    action: Optional[str] = Query("approve"),
    db: Session = Depends(get_db)
):
    """
    Human agent resolves an escalation ticket with one of three actions:

    - action: 'approve'
        Document is correct — AI was wrong. Mark the document as VERIFIED,
        unblock the onboarding session (move to next document or completion),
        and advance the conversation state.

    - action: 'request_reupload'
        Customer uploaded the wrong document. Reset the document status so
        the customer can upload the correct one. Send a clear message to the
        customer's chat specifying which document is required.

    - action: 'reject'
        Reject the onboarding application entirely.
    """
    try:
        esc_uuid = UUID(escalation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid escalation UUID format")

    esc = db.query(Escalation).filter(Escalation.id == esc_uuid).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")

    if esc.status == "resolved":
        return {
            "success": True,
            "id": str(esc.id),
            "escalation_id": str(esc.id),
            "message": "Escalation was already resolved.",
            "status": esc.status
        }

    resolved_action = "approve"
    notes = "Approved by human reviewer."
    agent = "human_agent"
    reupload_msg = None

    if payload:
        resolved_action = (payload.action or "approve").lower().strip()
        notes = payload.resolution_notes or notes
        agent = payload.resolved_by or agent
        reupload_msg = payload.reupload_message
    else:
        if action:
            resolved_action = action.lower().strip()
        if resolution_notes:
            notes = resolution_notes

    cust = db.query(Customer).filter(Customer.id == esc.customer_id).first()
    ctx = esc.context or {}
    doc_type = ctx.get("document_type")

    # ──────────────────────────────────────────────
    # ACTION: APPROVE — Document correct, AI was wrong
    # ──────────────────────────────────────────────
    if resolved_action == "approve":
        esc.status = "resolved"
        esc.resolution_notes = notes
        esc.resolved_by = agent
        esc.resolved_at = datetime.now()

        if cust:
            cust.status = "onboarding_resumed"

        if esc.session_id:
            st = db.query(OnboardingState).filter(
                OnboardingState.session_id == esc.session_id
            ).order_by(OnboardingState.created_at.desc()).first()

            if st:
                # Mark the document as verified in documents_status
                docs_st = dict(st.documents_status or {})
                if doc_type:
                    docs_st[doc_type] = "verified"
                    st.documents_status = docs_st
                    flag_modified(st, "documents_status")

                    # Also mark in Document table
                    doc_record = db.query(Document).filter(
                        Document.customer_id == esc.customer_id,
                        Document.document_type == doc_type
                    ).order_by(Document.uploaded_at.desc()).first()
                    if doc_record:
                        doc_record.status = "verified"
                        doc_record.verified_at = datetime.now()
                        doc_record.verification_notes = f"Manually approved by {agent}. {notes}"

                # Calculate what documents are remaining
                c_type = cust.customer_type if cust else (st.collected_info or {}).get("customer_type", "individual")
                required_docs = get_required_documents(c_type)
                missing_docs = [d for d in required_docs if docs_st.get(d) != "verified"]
                st.pending_items = missing_docs
                flag_modified(st, "pending_items")

                # Reset the failed attempt count for this document
                c_info = dict(st.collected_info or {})
                doc_attempts = dict(c_info.get("doc_attempts", {}))
                if doc_type and doc_type in doc_attempts:
                    del doc_attempts[doc_type]
                c_info["doc_attempts"] = doc_attempts

                # Remove old failure messages for this doc from chat history
                msgs = list(c_info.get("messages", []))
                doc_display = _doc_display(doc_type)

                def _is_failure_msg_for_doc(m):
                    content = (m.get("content") or "").lower()
                    return (
                        m.get("role") == "assistant"
                        and ("❌" in (m.get("content") or "") or "please provide correct" in content or "attempt" in content)
                        and (doc_type or "").replace("_", " ") in content
                    )

                cleaned_msgs = [m for m in msgs if not _is_failure_msg_for_doc(m)]

                if missing_docs:
                    next_doc = missing_docs[0]
                    next_doc_display = _doc_display(next_doc)
                    approval_message = (
                        f"✅ **{doc_display} has been manually verified and approved by our support team!**\n\n"
                        f"Now please upload your **{next_doc_display}** using the upload button below to proceed."
                    )
                    st.current_step = "collect_docs"
                else:
                    approval_message = (
                        f"✅ **{doc_display} has been manually verified and approved by our support team!**\n\n"
                        f"🎉 All required documents have been collected and verified! Moving to account activation."
                    )
                    st.current_step = "validate_docs"

                cleaned_msgs.append({"role": "assistant", "content": approval_message})
                c_info["messages"] = cleaned_msgs
                st.collected_info = c_info
                flag_modified(st, "collected_info")
                st.last_interaction_at = datetime.now()

                # Synchronize with active LangGraph execution if paused on this document's interrupt
                try:
                    graph = getattr(request.app.state, "graph", None)
                    if graph:
                        config = {"configurable": {"thread_id": esc.session_id}}
                        curr_graph_state = await graph.aget_state(config)
                        if curr_graph_state and curr_graph_state.tasks and any(t.interrupts for t in curr_graph_state.tasks):
                            resume_payload = {
                                "action": "upload_document",
                                "document_type": doc_type,
                                "status": "uploaded",
                                "verified": True
                            }
                            await graph.ainvoke(Command(resume=resume_payload), config=config)
                except Exception as ex:
                    print(f"[WARN] Advancing graph on escalation approval: {ex}", file=sys.stderr, flush=True)

    # ──────────────────────────────────────────────
    # ACTION: REQUEST RE-UPLOAD — Wrong document uploaded
    # ──────────────────────────────────────────────
    elif resolved_action == "request_reupload":
        esc.status = "resolved"
        esc.resolution_notes = notes
        esc.resolved_by = agent
        esc.resolved_at = datetime.now()

        if cust:
            cust.status = "onboarding_resumed"

        if esc.session_id:
            st = db.query(OnboardingState).filter(
                OnboardingState.session_id == esc.session_id
            ).order_by(OnboardingState.created_at.desc()).first()

            if st:
                # Remove the failed/escalated document entry so customer can re-upload
                if doc_type:
                    docs_st = dict(st.documents_status or {})
                    if doc_type in docs_st:
                        del docs_st[doc_type]
                    st.documents_status = docs_st
                    flag_modified(st, "documents_status")

                    # Delete the failed Document record from table so fresh upload is tracked
                    db.query(Document).filter(
                        Document.customer_id == esc.customer_id,
                        Document.document_type == doc_type,
                        Document.status != "verified"
                    ).delete(synchronize_session=False)

                # Reset attempt count for this document
                c_info = dict(st.collected_info or {})
                doc_attempts = dict(c_info.get("doc_attempts", {}))
                if doc_type and doc_type in doc_attempts:
                    del doc_attempts[doc_type]
                c_info["doc_attempts"] = doc_attempts

                # Build the re-upload message for the customer's chat
                doc_display = _doc_display(doc_type)
                if reupload_msg:
                    customer_message = reupload_msg
                else:
                    customer_message = (
                        f"🔄 **Re-upload Required: {doc_display}**\n\n"
                        f"Our support team has reviewed your submission. "
                        f"The document you uploaded does not match the required **{doc_display}**.\n\n"
                        f"Please upload the correct **{doc_display}** to continue your onboarding."
                    )

                # Remove old failure messages for this doc and add fresh re-upload request
                msgs = list(c_info.get("messages", []))

                def _is_old_failure_msg(m):
                    content = (m.get("content") or "").lower()
                    return (
                        m.get("role") == "assistant"
                        and ("❌" in (m.get("content") or "") or "attempt" in content or "please provide correct" in content)
                        and (doc_type or "").replace("_", " ") in content
                    )

                cleaned_msgs = [m for m in msgs if not _is_old_failure_msg(m)]
                cleaned_msgs.append({"role": "assistant", "content": customer_message})
                c_info["messages"] = cleaned_msgs

                c_type = cust.customer_type if cust else (st.collected_info or {}).get("customer_type", "individual")
                required_docs = get_required_documents(c_type)
                missing_docs = [d for d in required_docs if docs_st.get(d) != "verified"]
                if doc_type and doc_type in missing_docs:
                    missing_docs.remove(doc_type)
                    missing_docs.insert(0, doc_type)
                st.pending_items = missing_docs
                flag_modified(st, "pending_items")

                # Unblock the session step
                if st.current_step == "escalated":
                    st.current_step = "collect_docs"

                st.collected_info = c_info
                flag_modified(st, "collected_info")
                st.last_interaction_at = datetime.now()

    # ──────────────────────────────────────────────
    # ACTION: REJECT — Reject onboarding application
    # ──────────────────────────────────────────────
    elif resolved_action == "reject":
        esc.status = "rejected"
        esc.resolution_notes = notes
        esc.resolved_by = agent
        esc.resolved_at = datetime.now()
        if cust:
            cust.status = "rejected"

        if esc.session_id:
            st = db.query(OnboardingState).filter(
                OnboardingState.session_id == esc.session_id
            ).order_by(OnboardingState.created_at.desc()).first()

            if st:
                st.current_step = "rejected"
                st.pending_items = []
                flag_modified(st, "pending_items")

                c_info = dict(st.collected_info or {})
                c_info["customer_status"] = "rejected"
                c_info["is_rejected"] = True
                c_info["rejection_notes"] = notes

                msgs = list(c_info.get("messages", []))
                rejection_msg = (
                    f"❌ **Application Rejected**\n\n"
                    f"Your onboarding application has been reviewed and rejected by our verification team.\n\n"
                    f"**Reason / Notes:** {notes}\n\n"
                    f"This onboarding application is permanently closed. If you believe this is an error, please contact support."
                )
                msgs.append({"role": "assistant", "content": rejection_msg})
                c_info["messages"] = msgs
                st.collected_info = c_info
                flag_modified(st, "collected_info")
                st.last_interaction_at = datetime.now()

    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid action. Must be one of: 'approve', 'request_reupload', 'reject'"
        )

    db.commit()
    db.refresh(esc)

    return {
        "success": True,
        "id": str(esc.id),
        "escalation_id": str(esc.id),
        "action_taken": resolved_action,
        "escalation_status": esc.status,
        "customer_status": cust.status if cust else None,
        "resolution_notes": esc.resolution_notes,
        "resolved_at": esc.resolved_at.isoformat() if esc.resolved_at else None
    }
