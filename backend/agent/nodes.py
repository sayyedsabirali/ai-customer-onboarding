print("[LOAD] backend/agent/nodes.py is being imported")
from typing import Dict, Any, List
from uuid import UUID
from datetime import datetime
from sqlalchemy.orm import Session
from langgraph.types import interrupt
from agent.config import get_required_documents, get_display_name

from agent.state import AgentState
from agent.tools import (
    create_customer_tool,
    update_state_tool,
    validate_document_tool,
    trigger_task_tool,
    escalate_tool,
    get_onboarding_summary_tool,
    extract_onboarding_info_llm
)
from schemas import CustomerCreate
from database.connection import SessionLocal
from database.models import OnboardingState, Document, Customer

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def greeting_node(state: AgentState) -> AgentState:
    """
    Welcome the customer and initiate conversational onboarding.
    Pauses with interrupt() to wait for user's input.
    """
    messages = state.get("messages", [])
    collected = state.get("collected_info") or {}
    ctype = state.get("customer_type") or collected.get("customer_type")

    if ctype and str(ctype).lower() in ["individual", "startup", "enterprise"]:
        tier_display = str(ctype).capitalize()
        content = (
            f"👋 Welcome! I'm your AI Onboarding Assistant.\n\n"
            f"I'm here to help you get registered and set up your {tier_display} account. "
            f"To get started, please tell me your full name, or feel free to share your details!"
        )
        pending = [f for f in ["name", "email", "phone"] if f not in collected]
    else:
        content = (
            "👋 Welcome! I'm your AI Onboarding Assistant.\n\n"
            "I'm here to help you get registered and set up your account. "
            "To get started, could you please tell me your full name, or feel free to share your details!"
        )
        pending = ["name", "email", "phone", "customer_type"]

    greeting = {
        "role": "assistant",
        "content": content
    }
    if not messages or not any(m.get("role") == "assistant" and "welcome" in m.get("content", "").lower() for m in messages):
        messages.append(greeting)

    state["current_step"] = "greeting"
    state["messages"] = messages
    state["pending_items"] = pending
    state["response"] = greeting["content"]

    resume_value = interrupt({
        "action": "collect_info",
        "message": greeting["content"],
        "current_step": "greeting"
    })
    state["message"] = resume_value if resume_value else ""
    return state


def collect_info_node(state: AgentState) -> AgentState:
    """
    Intelligent conversational collection of customer information using Groq LLM.
    - Extracts multiple fields from natural multi-field messages in 1 turn
    - Deterministically validates newly extracted fields (email regex, phone digits, name length)
    - Fallback: supports single direct field answers (e.g. typing "Sabir" or "9876543210")
    - Automatically creates customer in DB when all 4 required fields are ready,
      and transitions seamlessly to document collection.
    """
    import re
    messages = state.get("messages", [])
    collected_info = state.get("collected_info") or {}
    
    # If state or collected_info already had customer_type, preserve it
    selected_tier = state.get("customer_type") or collected_info.get("customer_type")
    if selected_tier and str(selected_tier).lower() in ["individual", "startup", "enterprise"]:
        collected_info["customer_type"] = str(selected_tier).lower()
        state["customer_type"] = str(selected_tier).lower()

    required_fields = ["name", "email", "phone", "customer_type"]
    pending_items = [f for f in required_fields if f not in collected_info]
    user_input = (state.get("message", "") or "").strip()

    field_prompts = {
        "name": "Please tell me your full name.",
        "email": "What's your email address?",
        "phone": "What's your phone number?",
        "customer_type": "Are you registering as an individual, startup, or enterprise?"
    }

    conversational_reply = ""
    validation_errors = []

    if user_input:
        if not messages or messages[-1].get("content") != user_input or messages[-1].get("role") != "user":
            messages.append({"role": "user", "content": user_input})
            state["messages"] = messages

        # 1. Groq LLM Conversational Extraction
        llm_res = extract_onboarding_info_llm(user_input, collected_info, pending_items)
        extracted = llm_res.get("extracted", {})
        conversational_reply = llm_res.get("conversational_reply", "")

        # 2. Validate & Merge extracted fields (SUPPORTS CORRECTIONS & UPDATES)
        updates_made = []

        if "name" in extracted:
            name_val = str(extracted["name"]).strip()
            if len(name_val) >= 2 and any(c.isalpha() for c in name_val):
                old_name = collected_info.get("name")
                if old_name and old_name.lower() != name_val.lower():
                    updates_made.append(f"name updated to '{name_val}'")
                elif not old_name:
                    updates_made.append(f"name as '{name_val}'")
                collected_info["name"] = name_val
            else:
                validation_errors.append("❌ Name must be at least 2 characters long.")

        if "email" in extracted:
            email_val = str(extracted["email"]).strip()
            if re.match(r"^[\w\.-]+@[\w\.-]+\.\w{2,}$", email_val):
                # Immediate check: check if email already exists in DB
                db_chk = SessionLocal()
                try:
                    exists = db_chk.query(Customer).filter(Customer.email.ilike(email_val)).first()
                finally:
                    db_chk.close()

                if exists:
                    validation_errors.append(f"❌ An account with the email '{email_val}' already exists. Please provide a different email address.")
                    collected_info.pop("email", None)
                else:
                    old_email = collected_info.get("email")
                    if old_email and old_email.lower() != email_val.lower():
                        updates_made.append(f"email updated to '{email_val}'")
                    elif not old_email:
                        updates_made.append(f"email as '{email_val}'")
                    collected_info["email"] = email_val
            else:
                validation_errors.append(f"❌ '{email_val}' is an invalid email format. Please enter a valid email (e.g., name@domain.com).")

        if "phone" in extracted:
            phone_val = str(extracted["phone"]).strip()
            cleaned = phone_val.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "").strip()
            if cleaned.isdigit() and 10 <= len(cleaned) <= 15 and len(set(cleaned)) > 1:
                old_phone = collected_info.get("phone")
                if old_phone and old_phone != phone_val:
                    updates_made.append(f"phone updated to '{phone_val}'")
                elif not old_phone:
                    updates_made.append(f"phone as '{phone_val}'")
                collected_info["phone"] = phone_val
            else:
                validation_errors.append(f"❌ '{phone_val}' is invalid. Please provide a valid 10-digit phone number (e.g. 9876543210 or +919876543210).")

        if "customer_type" in extracted and extracted["customer_type"]:
            ctype = str(extracted["customer_type"]).lower().strip()
            if ctype in ["individual", "startup", "enterprise"]:
                old_ctype = collected_info.get("customer_type")
                if not old_ctype or old_ctype != ctype:
                    updates_made.append(f"account tier as '{ctype.capitalize()}'")
                collected_info["customer_type"] = ctype

        # Conversational fallback for account tier mention
        if "customer_type" not in collected_info:
            lower_input = user_input.lower()
            if "startup" in lower_input or "start-up" in lower_input:
                collected_info["customer_type"] = "startup"
                updates_made.append("account tier as 'Startup'")
            elif "enterprise" in lower_input or "corporate" in lower_input:
                collected_info["customer_type"] = "enterprise"
                updates_made.append("account tier as 'Enterprise'")
            elif "individual" in lower_input or "personal" in lower_input:
                collected_info["customer_type"] = "individual"
                updates_made.append("account tier as 'Individual'")

        if "company_name" in extracted:
            collected_info["company_name"] = str(extracted["company_name"]).strip()

        # 3. Explicit check: user attempted phone number but it's too short (e.g. "6543210")
        if "phone" not in collected_info:
            digits_found = re.findall(r"\d+", user_input)
            if digits_found and (pending_items and pending_items[0] == "phone" or "phone" in user_input.lower() or "number" in user_input.lower()):
                merged = "".join(digits_found)
                if len(merged) < 10 and not any("phone" in err.lower() for err in validation_errors):
                    validation_errors.append(f"❌ '{merged}' is only {len(merged)} digits. Please provide a valid 10-digit phone number (e.g. 9876543210 or +919876543210).")

        # 4. Fallback: single direct input if LLM didn't catch it and no validation errors
        if pending_items and not validation_errors and not extracted:
            current_field = pending_items[0]
            if current_field == "name" and "name" not in collected_info:
                if len(user_input) >= 2 and any(c.isalpha() for c in user_input) and len(user_input.split()) <= 5:
                    collected_info["name"] = user_input
            elif current_field == "email" and "email" not in collected_info:
                if re.match(r"^[\w\.-]+@[\w\.-]+\.\w{2,}$", user_input):
                    db_chk = SessionLocal()
                    try:
                        exists = db_chk.query(Customer).filter(Customer.email.ilike(user_input)).first()
                    finally:
                        db_chk.close()
                    if exists:
                        validation_errors.append(f"❌ An account with the email '{user_input}' already exists. Please provide a different email address.")
                    else:
                        collected_info["email"] = user_input
            elif current_field == "phone" and "phone" not in collected_info:
                cleaned = user_input.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "").strip()
                if cleaned.isdigit() and 10 <= len(cleaned) <= 15 and len(set(cleaned)) > 1:
                    collected_info["phone"] = user_input
            elif current_field == "customer_type" and "customer_type" not in collected_info:
                ctype_lower = user_input.lower().strip()
                if ctype_lower in ["individual", "startup", "enterprise"]:
                    collected_info["customer_type"] = ctype_lower

    # If there are validation errors on user's input, acknowledge what worked and ask for correction!
    if validation_errors:
        ack_part = ""
        if updates_made:
            ack_part = f"✅ I've noted your {', '.join(updates_made)}!\n\n"
        error_reply = ack_part + "\n".join(validation_errors)
        messages.append({"role": "assistant", "content": error_reply})
        state["response"] = error_reply
        state["messages"] = messages
        state["current_step"] = "collect_info"
        state["message"] = ""

        resume_value = interrupt({
            "action": "collect_info",
            "message": error_reply,
            "field": pending_items[0] if pending_items else "phone",
            "current_step": "collect_info"
        })
        state["message"] = resume_value if resume_value else ""
        return state

    # 4. Recompute remaining missing items
    pending_items = [f for f in required_fields if f not in collected_info]
    state["collected_info"] = collected_info
    state["pending_items"] = pending_items
    state["missing_info"] = pending_items

    # 5. Check if all required fields are now collected!
    if not pending_items:
        user_type = collected_info.get("customer_type", "individual")
        db = SessionLocal()
        result = create_customer_tool(db, CustomerCreate(
            name=collected_info.get("name", ""),
            email=collected_info.get("email", ""),
            phone=collected_info.get("phone", ""),
            company_name=collected_info.get("company_name", ""),
            customer_type=user_type
        ))

        if result["success"]:
            state["customer_id"] = result["customer_id"]
            pending_docs = get_required_documents(user_type)
            state["pending_items"] = pending_docs
            state["current_step"] = "collect_docs"

            first_doc = pending_docs[0].replace("_", " ").title() if pending_docs else "PAN Card"
            reg_msg = (
                f"🎉 **Awesome, {collected_info['name']}! Your profile is registered.**\n\n"
                f"📋 **Registration Details:**\n"
                f"• **Name:** {collected_info['name']}\n"
                f"• **Email:** {collected_info['email']}\n"
                f"• **Phone:** {collected_info['phone']}\n"
                f"• **Plan:** {user_type.capitalize()} Account\n\n"
                f"📄 **Next Step: Document Verification**\n"
                f"Please upload your **{first_doc}** using the upload button below to proceed."
            )
            if not messages or messages[-1].get("content") != reg_msg or messages[-1].get("role") != "assistant":
                messages.append({"role": "assistant", "content": reg_msg})
            state["response"] = reg_msg
            state["messages"] = messages
            state["current_step"] = "collect_docs"
            state["message"] = ""

            collected_info["messages"] = messages
            update_state_tool(
                db=db,
                customer_id=UUID(state["customer_id"]),
                session_id=state["session_id"],
                current_step="collect_docs",
                collected_info=collected_info,
                pending_items=pending_docs
            )
            db.close()
            return state
        else:
            db.close()
            error_msg = f"❌ {result['error']}. Please review your details."
            messages.append({"role": "assistant", "content": error_msg})
            state["response"] = error_msg
            state["messages"] = messages
            state["current_step"] = "collect_info"
            state["message"] = ""
            resume_value = interrupt({
                "action": "collect_info",
                "message": error_msg,
                "current_step": "collect_info"
            })
            state["message"] = resume_value if resume_value else ""
            return state

    # 6. Still missing fields: Acknowledge what was received and ask ONLY for remaining missing fields!
    name_so_far = collected_info.get("name")

    ack = ""
    if updates_made:
        updates_text = " and ".join([", ".join(updates_made[:-1]), updates_made[-1]]) if len(updates_made) > 1 else updates_made[0]
        if name_so_far and not any("name" in u for u in updates_made):
            ack = f"Thanks, **{name_so_far}**! I've noted your {updates_text}.\n\n"
        elif name_so_far:
            ack = f"Nice to meet you, **{name_so_far}**! 👋 I've noted your {updates_text}.\n\n"
        else:
            ack = f"Got it! I've noted your {updates_text}.\n\n"

    # Ask strictly for what is STILL in pending_items (NEVER re-ask what's already collected)
    if "name" in pending_items:
        ask_text = "Could you please tell me your **full name**?"
    elif "email" in pending_items and "phone" in pending_items:
        ask_text = "Could you please provide your **email address** and **10-digit phone number** next?"
    elif "email" in pending_items:
        ask_text = "Could you please provide your **email address** next?"
    elif "phone" in pending_items:
        ask_text = "Could you please provide your **10-digit phone number** to complete your registration?"
    elif "customer_type" in pending_items:
        ask_text = "To complete your registration, could you please let me know if you are registering as an **individual**, **startup**, or **enterprise**?"
    else:
        ask_text = "Please share any remaining details to complete your registration."

    question = ack + ask_text

    if not messages or messages[-1].get("content") != question or messages[-1].get("role") != "assistant":
        messages.append({"role": "assistant", "content": question})
    state["response"] = question
    state["messages"] = messages
    state["current_step"] = "collect_info"
    state["message"] = ""

    next_field = pending_items[0] if pending_items else "details"
    resume_value = interrupt({
        "action": "collect_info",
        "message": question,
        "field": next_field,
        "current_step": "collect_info"
    })
    state["message"] = resume_value if resume_value else ""
    return state


def validate_info_node(state: AgentState) -> AgentState:
    """
    Validate completeness and consistency of collected information.
    """
    collected_info = state.get("collected_info") or {}
    selected_tier = state.get("customer_type") or collected_info.get("customer_type")
    if selected_tier and str(selected_tier).lower() in ["individual", "startup", "enterprise"]:
        collected_info["customer_type"] = str(selected_tier).lower()
        state["customer_type"] = str(selected_tier).lower()

    pending_items = state.get("pending_items", [])
    missing_info = []
    
    required_fields = ["name", "email", "phone", "customer_type"]
    for field in required_fields:
        if not collected_info.get(field):
            missing_info.append(field)
    
    email = collected_info.get("email", "")
    if email and ("@" not in email or "." not in email):
        missing_info.append("email_format")
    
    if missing_info:
        response = f"⚠️ I need the following information: {', '.join(missing_info)}. Please provide it."
        messages.append({"role": "assistant", "content": response})
        state["response"] = response
        state["current_step"] = "collect_info"
        state["missing_info"] = missing_info
    else:
        customer_type = collected_info.get("customer_type", "individual")
        response = "✅ All information verified! Now let's collect your documents."
        messages.append({"role": "assistant", "content": response})
        state["response"] = response
        state["current_step"] = "collect_docs"
        state["pending_items"] = get_required_documents(customer_type)
        state["missing_info"] = []
    
    state["messages"] = messages
    state["collected_info"] = collected_info
    
    if state.get("customer_id"):
        db = SessionLocal()
        try:
            update_state_tool(
                db=db,
                customer_id=UUID(state["customer_id"]),
                session_id=state["session_id"],
                current_step=state["current_step"],
                collected_info=collected_info,
                pending_items=state.get("pending_items", []),
                missing_info=state.get("missing_info", [])
            )
        finally:
            db.close()
    
    return state

def document_collection_node(state: AgentState) -> AgentState:
    """
    Collect documents one at a time using single-interrupt loop pattern.

    Architecture:
    - Each invocation asks for ONE document and interrupts.
    - The routing edge (route_after_document_collection) loops back here
      if more documents are needed.
    - This avoids the LangGraph anti-pattern of multiple interrupt() calls
      in a single node.
    """
    messages = state.get("messages", [])
    documents_status = state.get("documents_status", {})
    customer_type = state.get("collected_info", {}).get("customer_type", "individual")
    required_docs = get_required_documents(customer_type)

    # Always read authoritative documents_status from DB.
    # The performance optimization was eliminating redundant WRITES, not reads.
    # Without this read, LangGraph in-memory state may not reflect docs verified via the /document endpoint.
    if state.get("customer_id"):
        db = SessionLocal()
        try:
            updated_state = db.query(OnboardingState).filter(
                OnboardingState.customer_id == UUID(state["customer_id"]),
                OnboardingState.session_id == state["session_id"]
            ).first()
            if updated_state and updated_state.documents_status:
                # Merge DB state with any in-memory verified state (take the most complete set)
                db_docs = updated_state.documents_status
                mem_docs = documents_status or {}
                # Any doc marked verified in either source stays verified
                merged = dict(db_docs)
                for k, v in mem_docs.items():
                    if v in ("verified", "escalated") or k not in merged:
                        merged[k] = v
                documents_status = merged
                state["documents_status"] = documents_status
        finally:
            db.close()

    # ---- Check which docs are still missing ----
    uploaded_docs = [doc for doc, status in documents_status.items()
                     if status in ["pending", "verified"]]
    missing_docs = [doc for doc in required_docs if doc not in uploaded_docs]

    if not missing_docs:
        # All documents collected — move to validation
        state["current_step"] = "validate_docs"
        state["pending_items"] = []
        response = "✅ All documents collected! Let me verify them."
        messages.append({"role": "assistant", "content": response})
        state["response"] = response
        state["messages"] = messages
        return state

    # ---- Ask for the next missing document ----
    next_doc = missing_docs[0]

    # Build acknowledgment if a previous doc was just uploaded
    prev_uploaded = [doc for doc in required_docs
                     if doc in uploaded_docs and doc not in missing_docs]
    if prev_uploaded:
        last_uploaded = prev_uploaded[-1]
        response = (
            f"✅ **{get_display_name(last_uploaded)} received and verified!**\n\n"
            f"Now please upload your **{get_display_name(next_doc)}** using the upload button below."
        )
        if not messages or messages[-1].get("content") != response or messages[-1].get("role") != "assistant":
            messages.append({"role": "assistant", "content": response})
        state["response"] = response
    else:
        curr_resp = state.get("response", "")
        if "registered" in curr_resp.lower() or "awesome" in curr_resp.lower():
            response = curr_resp
        else:
            response = f"📄 Please upload your **{get_display_name(next_doc)}** to proceed."
            if not messages or messages[-1].get("content") != response or messages[-1].get("role") != "assistant":
                messages.append({"role": "assistant", "content": response})
        state["response"] = response

    state["current_step"] = "collect_docs"
    state["pending_items"] = missing_docs
    state["messages"] = messages

    # ---- INTERRUPT — Wait for this ONE document ----
    resume_value = interrupt({
        "action": "upload_document",
        "document_type": next_doc,
        "customer_id": state.get("customer_id"),
        "message": response,
        "current_step": "collect_docs"
    })

    # If resume_value is a text chat message from /chat endpoint (e.g. user asking question or updating email/name)
    if isinstance(resume_value, str) and resume_value.strip():
        user_msg = resume_value.strip()
        if not messages or messages[-1].get("content") != user_msg or messages[-1].get("role") != "user":
            messages.append({"role": "user", "content": user_msg})
            state["messages"] = messages
        llm_res = extract_onboarding_info_llm(user_msg, state.get("collected_info", {}), [])
        extracted = llm_res.get("extracted", {})
        conversational_reply = llm_res.get("conversational_reply", "")

        collected_info = state.get("collected_info", {})
        updates_doc = []
        validation_errors = []

        # 1. Detect if user attempted to provide an invalid email (e.g. "sabirgmail.com" missing @)
        if "email" in user_msg.lower():
            words = user_msg.replace(",", " ").replace(";", " ").split()
            for w in words:
                w_clean = w.strip(".:,;()\"'")
                if ("gmail" in w_clean.lower() or "yahoo" in w_clean.lower() or "outlook" in w_clean.lower() or ".com" in w_clean.lower()) and "@" not in w_clean:
                    validation_errors.append(f"❌ '{w_clean}' is an invalid email (missing '@' symbol). Please enter a valid email address (e.g. name@domain.com).")

        # 2. Extract valid updates
        if "name" in extracted and len(extracted["name"]) >= 2:
            old = collected_info.get("name")
            collected_info["name"] = extracted["name"]
            updates_doc.append(f"name to '{extracted['name']}'")

        if "email" in extracted:
            import re
            if re.match(r"^[\w\.-]+@[\w\.-]+\.\w{2,}$", extracted["email"]):
                old = collected_info.get("email")
                collected_info["email"] = extracted["email"]
                updates_doc.append(f"email to '{extracted['email']}'")
            else:
                validation_errors.append(f"❌ '{extracted['email']}' is an invalid email format.")

        if "phone" in extracted:
            phone_val = str(extracted["phone"]).strip()
            cleaned = phone_val.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "").strip()
            if cleaned.isdigit() and 10 <= len(cleaned) <= 15 and len(set(cleaned)) > 1:
                collected_info["phone"] = phone_val
                updates_doc.append(f"phone to '{phone_val}'")
            else:
                validation_errors.append(f"❌ '{phone_val}' is an invalid phone number.")

        # CASE A: Validation errors on user's chat input
        if validation_errors:
            err_reply = "\n".join(validation_errors) + f"\n\n📄 Also, please upload your {get_display_name(next_doc)} to proceed."
            messages.append({"role": "assistant", "content": err_reply})
            state["response"] = err_reply
            state["messages"] = messages
            state["message"] = ""

            resume_value2 = interrupt({
                "action": "upload_document",
                "document_type": next_doc,
                "customer_id": state.get("customer_id"),
                "message": err_reply,
                "current_step": "collect_docs"
            })
            state["message"] = str(resume_value2) if resume_value2 else ""
            return state

        # CASE B: Successful field update
        if updates_doc:
            state["collected_info"] = collected_info
            if state.get("customer_id"):
                db = SessionLocal()
                try:
                    from database.models import Customer
                    cust = db.query(Customer).filter(Customer.id == UUID(state["customer_id"])).first()
                    if cust:
                        if "name" in collected_info: cust.name = collected_info["name"]
                        if "email" in collected_info: cust.email = collected_info["email"]
                        if "phone" in collected_info: cust.phone = collected_info["phone"]
                        db.commit()
                except Exception:
                    db.rollback()
                finally:
                    db.close()

            upd_reply = f"✅ Got it! I've updated your {', '.join(updates_doc)}. Please upload your {get_display_name(next_doc)} to continue."
            messages.append({"role": "assistant", "content": upd_reply})
            state["response"] = upd_reply
            state["messages"] = messages
            state["message"] = ""

            resume_value2 = interrupt({
                "action": "upload_document",
                "document_type": next_doc,
                "customer_id": state.get("customer_id"),
                "message": upd_reply,
                "current_step": "collect_docs"
            })
            state["message"] = str(resume_value2) if resume_value2 else ""
            return state

        # CASE C: General conversational question or remark
        if conversational_reply:
            reply_with_doc = f"{conversational_reply}\n\n📄 Please upload your {get_display_name(next_doc)} to continue."
            messages.append({"role": "assistant", "content": reply_with_doc})
            state["response"] = reply_with_doc
            state["messages"] = messages
            state["message"] = ""

            resume_value2 = interrupt({
                "action": "upload_document",
                "document_type": next_doc,
                "customer_id": state.get("customer_id"),
                "message": reply_with_doc,
                "current_step": "collect_docs"
            })
        # CASE D: Fallback for any other chat message while waiting for document
        fallback_reply = f"Thanks! 📄 Please upload your **{get_display_name(next_doc)}** using the upload button below to continue."
        messages.append({"role": "assistant", "content": fallback_reply})
        state["response"] = fallback_reply
        state["messages"] = messages
        state["message"] = ""

        resume_value2 = interrupt({
            "action": "upload_document",
            "document_type": next_doc,
            "customer_id": state.get("customer_id"),
            "message": fallback_reply,
            "current_step": "collect_docs"
        })
        state["message"] = str(resume_value2) if resume_value2 else ""
        return state

    elif isinstance(resume_value, dict) and resume_value.get("status") == "uploaded":
        doc_t = resume_value.get("document_type", "document")
        up_text = f"📎 Uploaded {get_display_name(doc_t)}"
        if not messages or messages[-1].get("content") != up_text or messages[-1].get("role") != "user":
            messages.append({"role": "user", "content": up_text})
            state["messages"] = messages
        # Keep temporary verification state in application/session state
        docs_st = dict(state.get("documents_status") or {})
        docs_st[doc_t] = "verified"
        state["documents_status"] = docs_st

    state["message"] = str(resume_value) if resume_value else ""
    return state


def document_validation_node(state: AgentState) -> AgentState:
    """
    Validate document content (basic consistency).
    Required docs resolved dynamically from customer_type via config.
    Checks for duplicates and escalates if found.
    """
    messages = state.get("messages", [])
    documents_status = state.get("documents_status", {})
    customer_id = state.get("customer_id")
    customer_type = state.get("collected_info", {}).get("customer_type", "individual")
    required_docs = get_required_documents(customer_type)

    if not customer_id:
        response = "❌ No customer found. Please restart the onboarding."
        messages.append({"role": "assistant", "content": response})
        state["response"] = response
        state["current_step"] = "error"
        state["messages"] = messages
        return state

    db = SessionLocal()

    try:
        all_docs = db.query(Document).filter(
            Document.customer_id == UUID(customer_id)
        ).all()

        for doc_type in required_docs:
            active_docs = [
                doc for doc in all_docs
                if doc.document_type == doc_type and doc.status in ["pending", "verified"]
            ]

            if len(active_docs) > 1:
                context = {
                    "document_type": doc_type,
                    "duplicate_count": len(active_docs),
                    "document_ids": [str(doc.id) for doc in active_docs],
                    "message": f"Multiple {doc_type} documents found. Manual review required."
                }

                result = escalate_tool(
                    db=db,
                    customer_id=UUID(customer_id),
                    reason=f"Duplicate {doc_type} documents detected",
                    context=context,
                    recommended_action="Review all documents and keep only one valid copy"
                )

                response = (
                    f"🆘 Multiple {get_display_name(doc_type)} documents detected. "
                    f"I've escalated this to a human agent. "
                    f"Reference: {result.get('escalation_id', 'ESC-001')}."
                )

                messages.append({"role": "assistant", "content": response})
                state["response"] = response
                state["current_step"] = "escalated"
                state["needs_escalation"] = True
                state["messages"] = messages

                db.close()
                return state

        uploaded_docs = [doc for doc, status in documents_status.items() if status in ["pending", "verified"]]
        missing_docs = [doc for doc in required_docs if doc not in uploaded_docs]

        if missing_docs:
            state["pending_items"] = missing_docs
            state["current_step"] = "collect_docs"

            response = f"📄 Still need: {', '.join([get_display_name(d) for d in missing_docs])}. Please upload."
            if not messages or messages[-1].get("content") != response or messages[-1].get("role") != "assistant":
                messages.append({"role": "assistant", "content": response})
            state["response"] = response
            state["messages"] = messages

            import copy
            coll_info = copy.deepcopy(state.get("collected_info") or {})
            coll_info["messages"] = messages

            update_state_tool(
                db=db,
                customer_id=UUID(customer_id),
                session_id=state["session_id"],
                current_step="collect_docs",
                collected_info=coll_info,
                pending_items=missing_docs,
                documents_status=documents_status
            )
            db.close()

        else:
            # Check if any documents in DB still need verification update
            unverified_docs = [d for d in all_docs if d.document_type in required_docs and d.status != "verified"]
            if unverified_docs:
                for doc in unverified_docs:
                    doc.status = "verified"
                    doc.verified_at = datetime.now()
                db.commit()

            for doc_type in required_docs:
                documents_status[doc_type] = "verified"

            state["pending_items"] = []
            state["documents_status"] = documents_status

            response = "✅ All documents validated! Now setting up your account..."
            if not messages or messages[-1].get("content") != response or messages[-1].get("role") != "assistant":
                messages.append({"role": "assistant", "content": response})
            state["response"] = response
            state["messages"] = messages
            state["current_step"] = "api_trigger"
            db.close()

    except Exception as e:
        db.close()
        response = f"❌ Error during document validation: {str(e)}"
        messages.append({"role": "assistant", "content": response})
        state["response"] = response
        state["current_step"] = "error"
        state["errors"] = state.get("errors", []) + [str(e)]

    state["messages"] = messages
    state["documents_status"] = documents_status

    return state


def api_trigger_node(state: AgentState) -> AgentState:
    """
    Trigger mock APIs for account setup.
    """
    messages = state.get("messages", [])
    customer_id = state.get("customer_id")
    
    if not customer_id:
        response = "❌ No customer found. Please restart the onboarding."
        messages.append({"role": "assistant", "content": response})
        state["response"] = response
        state["current_step"] = "error"
        return state
    
    db = SessionLocal()
    
    tasks = [
        {"type": "create_user_account", "endpoint": "/mock/create_account"},
        {"type": "setup_configuration", "endpoint": "/mock/setup_config"},
        {"type": "send_welcome_email", "endpoint": "/mock/send_email"}
    ]
    
    task_results = []
    all_success = True
    
    for task in tasks:
        result = trigger_task_tool(
            db=db,
            customer_id=UUID(customer_id),
            task_type=task["type"],
            api_endpoint=task["endpoint"],
            payload={"customer_id": customer_id}
        )
        task_results.append(result)
        if not result["success"]:
            all_success = False
    
    db.close()
    
    if all_success:
        response = "✅ All system tasks completed! Your onboarding is nearly complete."
        messages.append({"role": "assistant", "content": response})
        state["response"] = response
        state["current_step"] = "completion"
    else:
        response = "⚠️ Some tasks encountered issues. I'm escalating this to a human agent."
        messages.append({"role": "assistant", "content": response})
        state["response"] = response
        state["current_step"] = "escalation"
        state["needs_escalation"] = True
        state["escalation_reason"] = "API tasks failed"
        state["human_context"] = str(task_results)
    
    state["messages"] = messages
    state["tasks"] = task_results
    
    return state


def escalation_check_node(state: AgentState) -> AgentState:
    """
    Check if escalation is needed and escalate if required.
    """
    messages = state.get("messages", [])
    customer_id = state.get("customer_id")
    
    if state.get("needs_escalation", False):
        db = next(get_db())
        
        result = escalate_tool(
            db=db,
            customer_id=UUID(customer_id),
            reason=state.get("escalation_reason", "Unknown issue"),
            context={"state": state},
            recommended_action="Review the issue and resolve manually"
        )
        db.close()
        
        response = f"🆘 I've escalated this to a human agent. Reference: {result.get('escalation_id', 'ESC-001')}. They'll reach out to you shortly."
        messages.append({"role": "assistant", "content": response})
        state["response"] = response
        state["current_step"] = "escalated"
    
    state["messages"] = messages
    
    return state


def completion_node(state: AgentState) -> AgentState:
    """
    Mark onboarding as complete.
    """
    messages = state.get("messages", [])
    customer_id = state.get("customer_id")
    
    if customer_id:
        db = next(get_db())
        from database.models import Customer
        
        # Update customer status
        customer = db.query(Customer).filter(Customer.id == UUID(customer_id)).first()
        if customer:
            customer.status = "active"
            customer.completed_at = datetime.now()
        
        # Update onboarding_state to "complete"
        state_record = db.query(OnboardingState).filter(
            OnboardingState.customer_id == UUID(customer_id)
        ).order_by(OnboardingState.created_at.desc()).first()
        response = "🎉 Congratulations! Your onboarding is complete. You're now ready to use our product. A confirmation email has been sent to you."
        if not messages or messages[-1].get("content") != response or messages[-1].get("role") != "assistant":
            messages.append({"role": "assistant", "content": response})

        if state_record:
            state_record.current_step = "complete"
            import copy
            info = copy.deepcopy(state_record.collected_info or {})
            info["messages"] = messages
            state_record.collected_info = info
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(state_record, "collected_info")

        db.commit()
        db.close()
    else:
        response = "🎉 Congratulations! Your onboarding is complete. You're now ready to use our product. A confirmation email has been sent to you."
        if not messages or messages[-1].get("content") != response or messages[-1].get("role") != "assistant":
            messages.append({"role": "assistant", "content": response})

    state["messages"] = messages
    state["response"] = response
    state["current_step"] = "complete"

    return state


# ===== Routing Functions =====

def route_after_greeting(state: AgentState) -> str:
    return "collect_info"


def route_after_collect_info(state: AgentState) -> str:
    """
    Route after collect_info_node.
    - If info fields are still pending → stay in collect_info
    - If all info collected → go to validate_info
    - If already in document collection → go to collect_docs
    """
    current_step = state.get("current_step", "")
    
    # If already in document collection flow, route to collect_docs
    if current_step == "collect_docs":
        return "collect_docs"
    
    pending_items = state.get("pending_items", [])
    info_fields = ["name", "email", "phone", "customer_type"]
    if any(item in pending_items for item in info_fields):
        return "collect_info"
    return "validate_info"


def route_after_validate_info(state: AgentState) -> str:
    if state.get("missing_info"):
        return "collect_info"
    return "collect_docs"


def route_after_document_collection(state: AgentState) -> str:
    """
    Loop back to collect_docs if more documents are needed,
    otherwise proceed to validate_docs.
    """
    current_step = state.get("current_step", "")
    pending_items = state.get("pending_items", [])

    if current_step == "validate_docs" or not pending_items:
        return "validate_docs"
    return "collect_docs"


def route_after_document_validation(state: AgentState) -> str:
    pending_items = state.get("pending_items", [])
    current_step = state.get("current_step", "")
    
    if current_step == "escalated":
        return "end"
    
    if pending_items:
        return "collect_docs"
    return "api_trigger"


def route_after_api_trigger(state: AgentState) -> str:
    if state.get("needs_escalation", False):
        return "escalation"
    return "completion"


def route_after_escalation(state: AgentState) -> str:
    return "end"