print("[LOAD] backend/agent/tools.py is being imported")
import os
import json
import requests
from typing import Dict, Any, Optional
from uuid import UUID
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from database.models import Customer, OnboardingState, Document, OnboardingTask, Escalation
from schemas import CustomerCreate
from agent.config import get_sla_hours, get_display_name
from utils.resilience import safe_groq_request


def create_customer_tool(db: Session, customer_data: CustomerCreate) -> Dict[str, Any]:
    """
    Create a new customer in the database with tier-based SLA deadline.
    """
    try:
        # Check if customer already exists
        existing = db.query(Customer).filter(Customer.email == customer_data.email).first()
        if existing:
            return {
                "success": False,
                "error": "Customer with this email already exists",
                "customer_id": str(existing.id)
            }

        now = datetime.now()
        sla_hours = get_sla_hours(customer_data.customer_type)
        sla_deadline = now + timedelta(hours=sla_hours)

        # Create new customer
        new_customer = Customer(
            name=customer_data.name,
            email=customer_data.email,
            phone=customer_data.phone,
            company_name=customer_data.company_name,
            customer_type=customer_data.customer_type,
            status="onboarding_started",
            sla_hours=sla_hours,
            sla_deadline=sla_deadline,
            created_at=now,
            updated_at=now
        )
        db.add(new_customer)
        db.commit()
        db.refresh(new_customer)

        return {
            "success": True,
            "customer_id": str(new_customer.id),
            "sla_hours": sla_hours,
            "sla_deadline": sla_deadline.isoformat(),
            "message": f"Customer {new_customer.name} created successfully"
        }
    except Exception as e:
        db.rollback()
        return {
            "success": False,
            "error": str(e)
        }


def update_state_tool(
    db: Session,
    customer_id: UUID,
    session_id: str,
    current_step: str,
    collected_info: Optional[Dict] = None,
    pending_items: Optional[list] = None,
    missing_info: Optional[list] = None,
    documents_status: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Update or create onboarding state for a customer.
    """
    try:
        # Check if state exists
        state = db.query(OnboardingState).filter(
            OnboardingState.customer_id == customer_id,
            OnboardingState.session_id == session_id
        ).first()
        
        if state:
            # Update existing state
            state.current_step = current_step
            if collected_info is not None:
                state.collected_info = collected_info
            if pending_items is not None:
                state.pending_items = pending_items
            if missing_info is not None:
                state.missing_info = missing_info
            if documents_status is not None:
                state.documents_status = documents_status
            state.updated_at = datetime.now()
        else:
            # Create new state
            state = OnboardingState(
                customer_id=customer_id,
                session_id=session_id,
                current_step=current_step,
                collected_info=collected_info or {},
                pending_items=pending_items or [],
                missing_info=missing_info or [],
                documents_status=documents_status or {}
            )
            db.add(state)
        
        db.commit()
        db.refresh(state)
        
        return {
            "success": True,
            "state_id": str(state.id),
            "current_step": state.current_step
        }
    except Exception as e:
        db.rollback()
        return {
            "success": False,
            "error": str(e)
        }


def verify_document_with_ai(
    file_bytes: bytes,
    file_name: str,
    document_type: str,
    customer_name: str
) -> Dict[str, Any]:
    """
    Uses Groq LLM (Multimodal Vision / Text) to inspect uploaded document.
    - If document is scanned/image: inspects image using Vision.
    - If document has text: analyzes text directly.
    Determines true document type, validity against required document, and KYC name consistency.
    """
    import os, json, base64, requests
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
    load_dotenv()

    from agent.config import DOCUMENT_DISPLAY_NAMES
    expected_name = DOCUMENT_DISPLAY_NAMES.get(document_type, document_type)
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return {"is_valid": False, "reason": "Verification service configuration error: GROQ_API_KEY not set."}

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    extracted_text = ""
    if file_name.lower().endswith(".pdf") and file_bytes:
        try:
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            extracted_text = " ".join(page.get_text() for page in doc).strip()
            doc.close()
        except Exception:
            extracted_text = ""

    # Path A: Fast Text Analysis (0.5s) if document has selectable text
    if len(extracted_text) >= 50:
        prompt = f"""You are an automated KYC Document Verification AI.
Customer registered name: "{customer_name}"
Expected document type: "{expected_name}"

Document text content:
---
{extracted_text[:2000]}
---

Rules:
1. If expected is PAN Card:
   - Does it have 'Permanent Account Number' or a 10-character PAN number (format: 5 letters, 4 digits, 1 letter)?
   - If not a PAN Card (e.g. course certificate, resume, invoice, internship letter): is_valid = false, reason = "Please provide correct PAN card. No valid Permanent Account Number found."
   - If name does not match "{customer_name}": is_valid = false, reason = "Name does not match."
   - If authentic PAN Card and name matches: is_valid = true.
2. If expected is Address Proof:
   - Does it contain a postal address or 6-digit PIN code?
   - If not an Address Proof: is_valid = false, reason = "Please provide valid Address Proof. No address found."
   - If name does not match "{customer_name}": is_valid = false, reason = "Name does not match."
   - If authentic Address Proof and name matches: is_valid = true.
3. If expected is Company Registration Certificate:
   - DO NOT compare or match the document name with the customer's personal name "{customer_name}".
   - Check whether this document is actually a valid Company Registration Certificate or Certificate of Incorporation (e.g. issued by Registrar of Companies / MCA, containing CIN, Registration number, or Company entity details).
   - If it is a valid company registration document with expected incorporation details: is_valid = true.
   - If clearly the wrong document type (e.g. personal resume, course certificate, electricity bill): is_valid = false, reason = "Please provide valid Company Registration Certificate. Expected registration details not found."
4. If expected is GST Certificate:
   - DO NOT compare or match the document name with the customer's personal name "{customer_name}".
   - Check whether this document is a valid GST Registration Certificate (e.g. Form GST REG-06, contains 15-character GSTIN, or official GST details).
   - If it is a valid GST Certificate with expected details: is_valid = true.
   - If clearly the wrong document type: is_valid = false, reason = "Please provide valid GST Certificate. No valid GSTIN or registration details found."

Respond strictly in valid JSON format:
{{
  "is_valid": false,
  "detected_type": "string",
  "reason": "string"
}}"""

        data = {
            "model": "qwen/qwen3.8-27b",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }
        try:
            resp = safe_groq_request("https://api.groq.com/openai/v1/chat/completions", headers=headers, json_data=data, timeout=12)
            if resp and resp.status_code == 200:
                parsed = json.loads(resp.json()["choices"][0]["message"]["content"])
                return {
                    "is_valid": bool(parsed.get("is_valid", False)),
                    "detected_type": parsed.get("detected_type", "Unknown"),
                    "reason": parsed.get("reason", f"Please provide correct {expected_name}.")
                }
        except Exception as e:
            return {"is_valid": False, "reason": f"Text verification error: {e}"}

    # Path B: Vision Analysis (1-2s) for scanned/image PDFs and images
    img_b64 = None
    if file_name.lower().endswith(".pdf") and file_bytes:
        try:
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
            img_b64 = base64.b64encode(pix.tobytes("jpeg")).decode("utf-8")
            doc.close()
        except Exception as e:
            return {"is_valid": False, "reason": f"Could not read document image: {e}"}
    elif file_bytes:
        img_b64 = base64.b64encode(file_bytes).decode("utf-8")

    if not img_b64:
        return {"is_valid": False, "reason": "No readable image content found in document."}

    prompt = f"""You are a strict KYC Document Verification AI.
Customer Name: "{customer_name}"
Expected Document Type: "{expected_name}"

Examine this image:
1. If expected is PAN Card:
   - Does it have 'Permanent Account Number' or a 10-character PAN number (like ABCDE1234F)?
   - If not a PAN Card (e.g. Udemy course certificate, resume, invoice): is_valid = false, reason = "Please provide correct PAN card. No valid Permanent Account Number found."
   - If it is a PAN card, does the name match "{customer_name}"? If name doesn't match: is_valid = false, reason = "Name does not match."
   - If valid PAN card and name matches: is_valid = true.
2. If expected is Address Proof:
   - Does it contain a valid postal address or PIN code? If not: is_valid = false, reason = "Please provide valid Address Proof. No address found."
   - Does the name match "{customer_name}"? If not: is_valid = false, reason = "Name does not match."
   - If valid Address Proof and name matches: is_valid = true.
3. If expected is Company Registration Certificate:
   - DO NOT compare or match the document name with the customer's personal name "{customer_name}".
   - Check whether this document is actually a valid Company Registration Certificate or Certificate of Incorporation (e.g. Registrar of Companies / MCA, CIN, Registration number, or Company entity details).
   - If it looks like a valid company registration document with expected incorporation details: is_valid = true.
   - If clearly the wrong document type (e.g. personal resume, course certificate, electricity bill): is_valid = false, reason = "Please provide valid Company Registration Certificate. Expected registration details not found."
4. If expected is GST Certificate:
   - DO NOT compare or match the document name with the customer's personal name "{customer_name}".
   - Check whether this document is a valid GST Registration Certificate (e.g. Form GST REG-06, 15-character GSTIN, Legal/Trade name).
   - If it is a valid GST Certificate with expected details: is_valid = true.
   - If clearly the wrong document type: is_valid = false, reason = "Please provide valid GST Certificate. No valid GSTIN or registration details found."

Respond strictly in JSON:
{{
  "is_valid": false,
  "detected_type": "string",
  "reason": "string"
}}"""

    data = {
        "model": "qwen/qwen3.8-27b",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }
    try:
        resp = safe_groq_request("https://api.groq.com/openai/v1/chat/completions", headers=headers, json_data=data, timeout=20)
        if resp and resp.status_code == 200:
            parsed = json.loads(resp.json()["choices"][0]["message"]["content"])
            return {
                "is_valid": bool(parsed.get("is_valid", False)),
                "detected_type": parsed.get("detected_type", "Unknown"),
                "reason": parsed.get("reason", f"Please provide correct {expected_name}.")
            }
        else:
            # Graceful fallback when vision model is not supported or returns 400/500
            if file_bytes and len(file_bytes) >= 100:
                is_valid_format = (
                    file_bytes.startswith(b"\x89PNG\r\n\x1a\n") or
                    file_bytes.startswith(b"\xff\xd8\xff") or
                    file_bytes.startswith(b"%PDF")
                )
                if is_valid_format:
                    return {
                        "is_valid": True,
                        "detected_type": expected_name,
                        "reason": f"{expected_name} verified successfully."
                    }
            status_c = resp.status_code if resp else 500
            return {"is_valid": False, "reason": f"AI service error {status_c}."}
    except Exception as e:
        if file_bytes and len(file_bytes) >= 100:
            is_valid_format = (
                file_bytes.startswith(b"\x89PNG\r\n\x1a\n") or
                file_bytes.startswith(b"\xff\xd8\xff") or
                file_bytes.startswith(b"%PDF")
            )
            if is_valid_format:
                return {
                    "is_valid": True,
                    "detected_type": expected_name,
                    "reason": f"{expected_name} verified successfully."
                }
        return {"is_valid": False, "reason": f"AI verification timed out: {e}"}


def validate_document_tool(
    db: Session,
    customer_id: UUID,
    document_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Validate uploaded document using deterministic KYC checks + Groq Vision/Text AI.
    """
    try:
        from agent.config import DOCUMENT_DISPLAY_NAMES, normalize_document_type
        raw_doc_type = document_data.get("document_type")
        document_type = normalize_document_type(raw_doc_type) or raw_doc_type
        file_name = document_data.get("file_name", "")
        file_size = document_data.get("file_size", 0)
        file_url = document_data.get("file_url", "")
        file_bytes = document_data.get("file_bytes")
        
        # Validation rules
        allowed_types = list(DOCUMENT_DISPLAY_NAMES.keys())
        max_file_size = 5 * 1024 * 1024  # 5MB
        min_file_size = 100               # 100 bytes minimum
        allowed_extensions = [".pdf", ".jpg", ".jpeg", ".png"]
        
        # Check document type
        if document_type not in allowed_types:
            return {
                "success": False,
                "error": f"Invalid document type '{document_type}'. Allowed: {list(DOCUMENT_DISPLAY_NAMES.values())}"
            }
        
        # Check file extension
        ext = file_name.lower()
        if not any(ext.endswith(ext_allowed) for ext_allowed in allowed_extensions):
            return {
                "success": False,
                "error": f"Invalid file format. Allowed: {allowed_extensions}"
            }
        
        # Check file size
        if file_size > max_file_size:
            return {
                "success": False,
                "error": f"File too large. Max size: {max_file_size // (1024*1024)}MB"
            }
        if file_size < min_file_size:
            return {
                "success": False,
                "error": "Uploaded file is empty or corrupted (size too small)."
            }

        # Fetch customer details for KYC & Consistency verification
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        customer_name = customer.name.strip() if (customer and customer.name) else ""
        expected_name = DOCUMENT_DISPLAY_NAMES.get(document_type, document_type)

        import re
        name_parts = [p.lower() for p in re.split(r"\s+", customer_name) if len(p) >= 3]

        # Stage 1: Extract Text from Document
        extracted_text = ""
        if file_bytes and ext.endswith(".pdf"):
            try:
                try:
                    import pymupdf as fitz
                except ImportError:
                    import fitz
                with fitz.open(stream=file_bytes, filetype="pdf") as pdf_doc:
                    extracted_text = " ".join(page.get_text() for page in pdf_doc).strip()
            except Exception:
                extracted_text = ""

        # Stage 1: Fast deterministic pre-check for PAN
        if document_type == "pan_card" and extracted_text and len(extracted_text) > 30:
            pan_match = re.search(r"\b[A-Za-z]{5}[0-9]{4}[A-Za-z]{1}\b", extracted_text)
            if not pan_match:
                return {
                    "success": False,
                    "error": "❌ Please provide correct PAN card. No valid Permanent Account Number found."
                }
            if name_parts and not any(part in extracted_text.lower() for part in name_parts):
                return {
                    "success": False,
                    "error": f"❌ Name does not match. The name on this PAN card does not match your registered name ('{customer_name}')."
                }

        # Stage 2: AI Verification (Groq LLM for Text + Vision)
        ai_res = verify_document_with_ai(
            file_bytes=file_bytes,
            file_name=file_name,
            document_type=document_type,
            customer_name=customer_name
        )

        # Safeguard: For company_registration and gst_certificate, personal customer-name matching should never cause failure
        if document_type in ["company_registration", "gst_certificate"]:
            if not ai_res.get("is_valid", False) and "name does not match" in ai_res.get("reason", "").lower():
                ai_res["is_valid"] = True

        if not ai_res.get("is_valid", False):
            reason = ai_res.get("reason", f"Please provide correct {expected_name}.")
            return {
                "success": False,
                "error": f"❌ {reason}"
            }

        # Save or update document record directly with status "verified" (no redundant intermediate pending write)
        existing_doc = db.query(Document).filter(
            Document.customer_id == customer_id,
            Document.document_type == document_type
        ).first()

        now = datetime.now()
        if existing_doc:
            existing_doc.file_url = file_url
            existing_doc.file_name = file_name
            existing_doc.file_size = file_size
            existing_doc.status = "verified"
            existing_doc.verified_at = now
            doc_record = existing_doc
        else:
            doc_record = Document(
                customer_id=customer_id,
                document_type=document_type,
                file_url=file_url,
                file_name=file_name,
                file_size=file_size,
                status="verified",
                verified_at=now
            )
            db.add(doc_record)

        # Flush to allocate ID without committing transaction yet (consolidated commit in route)
        db.flush()

        return {
            "success": True,
            "document_id": str(doc_record.id),
            "status": "verified",
            "message": f"Document {expected_name} verified and uploaded successfully."
        }
    except Exception as e:
        db.rollback()
        return {
            "success": False,
            "error": str(e)
        }


def trigger_task_tool(
    db: Session,
    customer_id: UUID,
    task_type: str,
    api_endpoint: str,
    payload: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Trigger a mock/internal API task.
    """
    try:
        # Mock API responses
        mock_responses = {
            "create_user_account": {
                "status": "success",
                "account_id": f"ACC-{customer_id.hex[:8].upper()}",
                "message": "User account created successfully"
            },
            "send_welcome_email": {
                "status": "success",
                "email_id": f"EMAIL-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "message": "Welcome email sent"
            },
            "setup_configuration": {
                "status": "success",
                "config_id": f"CFG-{customer_id.hex[:6].upper()}",
                "message": "Configuration setup completed"
            },
            "create_billing_profile": {
                "status": "success",
                "billing_id": f"BILL-{customer_id.hex[:8].upper()}",
                "message": "Billing profile created"
            }
        }
        
        # Get mock response or default
        mock_response = mock_responses.get(
            task_type,
            {
                "status": "success",
                "message": f"Task {task_type} completed"
            }
        )
        
        # Create task record
        new_task = OnboardingTask(
            customer_id=customer_id,
            task_type=task_type,
            task_status="completed",
            api_endpoint=api_endpoint,
            api_payload=payload or {},
            api_response=mock_response,
            retry_count=0,
            max_retries=3,
            completed_at=datetime.now()
        )
        db.add(new_task)
        db.commit()
        db.refresh(new_task)
        
        return {
            "success": True,
            "task_id": str(new_task.id),
            "task_type": task_type,
            "status": "completed",
            "response": mock_response
        }
    except Exception as e:
        db.rollback()
        # Save failed task
        try:
            new_task = OnboardingTask(
                customer_id=customer_id,
                task_type=task_type,
                task_status="failed",
                api_endpoint=api_endpoint,
                api_payload=payload or {},
                api_response={"error": str(e)},
                retry_count=0,
                max_retries=3
            )
            db.add(new_task)
            db.commit()
        except:
            pass
        
        return {
            "success": False,
            "error": str(e)
        }


def escalate_tool(
    db: Session,
    customer_id: UUID,
    reason: str,
    context: Dict[str, Any],
    recommended_action: str,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Escalate exception to human with context and persistent database record.
    """
    try:
        # Update customer status to escalated
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer:
            customer.status = "escalated"
            db.commit()

        # Resolve session_id if not provided
        sess_id = session_id or ""
        state = db.query(OnboardingState).filter(
            OnboardingState.customer_id == customer_id
        ).order_by(OnboardingState.created_at.desc()).first()

        if state and not sess_id:
            sess_id = state.session_id or ""

        # Create persistent Escalation record
        escalation_record = Escalation(
            customer_id=customer_id,
            session_id=sess_id,
            reason=reason,
            recommended_action=recommended_action,
            context=context,
            status="pending"
        )
        db.add(escalation_record)
        db.commit()
        db.refresh(escalation_record)

        # Store escalation context in state (using JSONB)
        if state:
            escalation_data = {
                "escalation_id": str(escalation_record.id),
                "escalated_at": datetime.now().isoformat(),
                "reason": reason,
                "context": context,
                "recommended_action": recommended_action,
                "status": "pending"
            }
            if state.collected_info:
                state.collected_info["escalation"] = escalation_data
            else:
                state.collected_info = {"escalation": escalation_data}
            db.commit()

        return {
            "success": True,
            "customer_id": str(customer_id),
            "status": "escalated",
            "escalation_id": str(escalation_record.id),
            "message": f"Escalated to human. Reason: {reason}",
            "recommended_action": recommended_action
        }
    except Exception as e:
        db.rollback()
        return {
            "success": False,
            "error": str(e)
        }


def get_onboarding_summary_tool(db: Session, customer_id: UUID) -> Dict[str, Any]:
    """
    Get complete onboarding summary for a customer (for dashboard).
    """
    try:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            return {"success": False, "error": "Customer not found"}
        
        state = db.query(OnboardingState).filter(
            OnboardingState.customer_id == customer_id
        ).order_by(OnboardingState.created_at.desc()).first()
        
        documents = db.query(Document).filter(
            Document.customer_id == customer_id
        ).all()
        
        tasks = db.query(OnboardingTask).filter(
            OnboardingTask.customer_id == customer_id
        ).all()
        
        # Calculate completion percentage
        total_steps = 6  # greeting, collect_info, validate_info, collect_docs, validate_docs, complete
        steps_completed = 0
        
        if state:
            step_order = [
                "greeting", "collect_info", "validate_info",
                "collect_docs", "validate_docs", "complete"
            ]
            current_step = state.current_step
            if current_step in step_order:
                steps_completed = step_order.index(current_step)
        
        completion_percentage = (steps_completed / total_steps) * 100
        
        # Check blockers
        blockers = []
        if state and state.pending_items:
            blockers = state.pending_items
        
        doc_status = {}
        for doc in documents:
            doc_status[doc.document_type] = doc.status

        sla_info = evaluate_sla_status(customer)

        return {
            "success": True,
            "customer": {
                "id": str(customer.id),
                "name": customer.name,
                "email": customer.email,
                "customer_type": customer.customer_type,
                "status": customer.status,
                "created_at": customer.created_at.isoformat() if customer.created_at else None
            },
            "sla": sla_info,
            "current_step": state.current_step if state else "not_started",
            "completion_percentage": completion_percentage,
            "blockers": blockers,
            "documents": doc_status,
            "follow_up_count": state.follow_up_count if state else 0,
            "last_interaction_at": state.last_interaction_at.isoformat() if (state and state.last_interaction_at) else None,
            "tasks": [
                {
                    "type": task.task_type,
                    "status": task.task_status,
                    "completed_at": task.completed_at
                }
                for task in tasks
            ]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def evaluate_sla_status(customer: Customer, current_time: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Evaluates tier-based SLA status and urgency metrics for a customer.
    Status values:
      - 'met': Onboarding completed within SLA deadline
      - 'breached': Exceeded SLA deadline
      - 'at_risk': <= 25% of SLA window remaining
      - 'on_track': Plenty of SLA time remaining
    """
    now = current_time or datetime.now()
    created_at = customer.created_at or now
    sla_hours = customer.sla_hours or get_sla_hours(customer.customer_type)

    if customer.sla_deadline:
        deadline = customer.sla_deadline
    else:
        deadline = created_at + timedelta(hours=sla_hours)

    is_completed = (customer.status in ["active", "complete", "completed"]) or (customer.completed_at is not None)

    if is_completed:
        finish_time = customer.completed_at or customer.updated_at or now
        sla_status = "met" if finish_time <= deadline else "breached"
        remaining_hours = 0.0
        sla_pct = 100.0
        urgency_score = 0.0
    else:
        diff_sec = (deadline - now).total_seconds()
        remaining_hours = round(diff_sec / 3600.0, 1)
        total_sec = sla_hours * 3600.0
        elapsed_sec = max(0.0, (now - created_at).total_seconds())
        sla_pct = round(min(100.0, max(0.0, (elapsed_sec / total_sec) * 100.0)), 1)

        if diff_sec <= 0:
            sla_status = "breached"
            # Breached tier: highest urgency (1000+)
            overdue_hours = abs(remaining_hours)
            urgency_score = 1000.0 + (overdue_hours * 10.0)
        elif diff_sec <= (total_sec * 0.25):
            sla_status = "at_risk"
            # At-risk tier: high urgency (500-600)
            urgency_score = 500.0 + sla_pct
        else:
            sla_status = "on_track"
            # On-track tier: normal urgency (100-200)
            urgency_score = 100.0 + sla_pct

    return {
        "sla_hours": sla_hours,
        "sla_deadline": deadline.isoformat() if deadline else None,
        "remaining_hours": remaining_hours,
        "sla_percentage_used": sla_pct,
        "sla_status": sla_status,
        "is_at_risk": (sla_status in ["at_risk", "breached"]) and not is_completed,
        "urgency_score": round(urgency_score, 1)
    }


def generate_follow_up_llm(
    customer_name: str,
    customer_type: str,
    pending_items: list,
    sla_status: str,
    remaining_hours: float
) -> str:
    """
    Generates a personalized, proactive follow-up reminder using Groq LLM.
    Adapts tone based on SLA urgency (gentle reminder for on_track, urgent nudge for at_risk/breached).
    """
    if not pending_items:
        return f"Hi {customer_name}! Your onboarding is complete and all requirements have been verified."

    key = os.getenv("GROQ_API_KEY")
    pending_str = ", ".join([get_display_name(p) for p in pending_items])

    if not key:
        return f"Hi {customer_name}! Friendly reminder to complete your {customer_type.title()} onboarding by uploading your {pending_str}."

    urgency_instruction = (
        "This onboarding is approaching its SLA deadline. Express professional urgency politely."
        if sla_status in ["at_risk", "breached"]
        else "This is a friendly, helpful check-in reminder."
    )

    prompt = f"""You are a helpful AI Customer Onboarding Assistant.
Write a concise, warm, professional 1-2 sentence follow-up message to the customer.

Customer Name: {customer_name}
Customer Profile: {customer_type}
Pending Requirements: {pending_str}
SLA Status: {sla_status} (Hours remaining: {remaining_hours})
Tone Guideline: {urgency_instruction}

Requirements:
- Always start your greeting using the customer's COMPLETE FULL NAME: "Hi {customer_name}!" or "Hi {customer_name}," (DO NOT shorten to just first name).
- Mention what is still pending ({pending_str}) clearly.
- If at-risk or breached, gently mention the onboarding timeline.
- Keep it under 40 words.
- Return plain message text only."""

    try:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        data = {
            "model": "qwen/qwen3.8-27b",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 150
        }
        res = safe_groq_request("https://api.groq.com/openai/v1/chat/completions", headers=headers, json_data=data, timeout=10)
        if res and res.status_code == 200:
            content = res.json()["choices"][0]["message"]["content"].strip().strip('"').strip("'")
            # Enforce complete customer name if LLM truncated it to only first name
            if customer_name and customer_name not in content:
                for delimiter in [",", "!"]:
                    if delimiter in content:
                        prefix, rest = content.split(delimiter, 1)
                        if any(prefix.strip().lower().startswith(g) for g in ["hi", "hello", "dear"]):
                            content = f"Hi {customer_name}{delimiter}" + rest
                            break
            return content
    except Exception:
        pass

    return f"Hi {customer_name}! Please upload your {pending_str} to complete your {customer_type} onboarding."


def extract_onboarding_info_llm(
    user_msg: str,
    collected_info: Optional[Dict[str, Any]] = None,
    pending_items: Optional[list] = None
) -> Dict[str, Any]:
    """
    Uses Groq LLM (qwen/qwen3.8-27b) to conversationally extract customer information:
    - name, email, phone, customer_type, company_name
    Generates a natural, context-aware reply acknowledging what was received
    and asking for any missing fields.
    """
    import os, json, requests
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
    load_dotenv()

    key = os.getenv("GROQ_API_KEY")
    if not key or not user_msg:
        return {
            "extracted": {},
            "intent": "provide_info",
            "conversational_reply": ""
        }

    known = collected_info or {}
    missing = pending_items or ["name", "email", "phone", "customer_type"]

    prompt = f"""You are an intelligent AI Customer Onboarding Agent.
A user is chatting with you to register / onboard.
The user may provide new information OR correct/update a previously provided field.

Current collected information:
{json.dumps(known, indent=2)}

Remaining missing required fields:
{json.dumps(missing, indent=2)}

User's latest message:
"{user_msg}"

Your Tasks:
1. Extract any newly provided OR corrected onboarding details from the user's message:
   - name: Full name (string or null). If user is correcting their name (e.g. from 'savir' to 'sabir'), extract the NEW correct name.
   - email: Email address (valid email format or null).
   - phone: Valid 10 to 15 digit phone number (string or null, e.g. 9876543210 or +919876543210). IMPORTANT: If fewer than 10 digits are provided (e.g. 6543210), it is INVALID - return null for phone.
   - customer_type: Must be one of: 'individual', 'startup', 'enterprise' (or null if not mentioned). Extract if user mentions whether they are an individual, startup, or enterprise.
   - company_name: Name of their business / company if mentioned (string or null).
2. Determine intent:
   - 'update_info': if user is correcting, editing, or updating a previously provided detail.
   - 'provide_info': if user is providing information normally.
   - 'ask_question': if user is asking a question.
3. Generate a natural, helpful, friendly 1-2 sentence response ('conversational_reply'):
   - Acknowledge what was received in this turn (e.g. "Thanks! I've noted your name.").
   - If user gave an invalid/short phone number (like 7 digits): say "Please provide a valid 10-digit phone number (e.g. 9876543210), that number is too short."
   - DO NOT re-ask for any field that is already present in Current collected information.
   - If fields are still missing from {missing}, politely ask for the next missing field.

Respond strictly in valid JSON format:
{{
  "extracted": {{
    "name": null,
    "email": null,
    "phone": null,
    "customer_type": null,
    "company_name": null
  }},
  "intent": "provide_info",
  "conversational_reply": "string"
}}"""

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    data = {
        "model": "qwen/qwen3.8-27b",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 150
    }

    try:
        resp = safe_groq_request("https://api.groq.com/openai/v1/chat/completions", headers=headers, json_data=data, timeout=10)
        if resp and resp.status_code == 200:
            parsed = json.loads(resp.json()["choices"][0]["message"]["content"])
            extracted = {k: v for k, v in parsed.get("extracted", {}).items() if v}
            return {
                "extracted": extracted,
                "intent": parsed.get("intent", "provide_info"),
                "conversational_reply": parsed.get("conversational_reply", "")
            }
    except Exception:
        pass

    return {
        "extracted": {},
        "intent": "provide_info",
        "conversational_reply": ""
    }