import sys, uuid, asyncio
sys.path.insert(0, "backend")

from datetime import datetime, timedelta
from database.connection import SessionLocal
from database.models import Customer, OnboardingState
from agent.tools import create_customer_tool, evaluate_sla_status, generate_follow_up_llm
from schemas import CustomerCreate
from routes.onboarding import trigger_single_follow_up, get_operational_dashboard
from fastapi import HTTPException

print("=" * 80)
print("REGRESSION TEST: FOLLOW-UP LOGIC (COMPLETED VS INCOMPLETE SESSIONS)")
print("=" * 80)

db = SessionLocal()

try:
    # -------------------------------------------------------------
    # 1. Test Incomplete Customer with Pending Items (Should Allow Follow-up)
    # -------------------------------------------------------------
    print("\n--- 1. INCOMPLETE CUSTOMER (PENDING ITEMS) ---")
    inc_email = f"inc_{uuid.uuid4().hex[:6]}@example.com"
    inc_res = create_customer_tool(db, CustomerCreate(
        name="Incomplete Customer",
        email=inc_email,
        phone="9876543210",
        customer_type="individual"
    ))
    inc_cid = uuid.UUID(inc_res["customer_id"])
    inc_sid = f"sess-inc-{uuid.uuid4().hex[:8]}"

    inc_state = OnboardingState(
        customer_id=inc_cid,
        session_id=inc_sid,
        current_step="collect_docs",
        pending_items=["pan_card", "address_proof"],
        collected_info={"name": "Incomplete Customer", "customer_type": "individual"}
    )
    db.add(inc_state)
    db.commit()

    # Trigger follow-up: should succeed
    fu_inc = asyncio.run(trigger_single_follow_up(session_id=inc_sid, db=db))
    assert fu_inc["success"] is True
    assert fu_inc["follow_up_count"] == 1
    safe_msg = fu_inc["follow_up_message"].encode("ascii", "replace").decode("ascii")
    print(f"Follow-up for Incomplete Customer: SUCCESS | Count: {fu_inc['follow_up_count']}")
    print(f"Message: \"{safe_msg}\"")
    assert "pan" in fu_inc["follow_up_message"].lower() or "address" in fu_inc["follow_up_message"].lower() or "document" in fu_inc["follow_up_message"].lower()
    print("[PASS] Incomplete customer received appropriate pending document follow-up!")

    # -------------------------------------------------------------
    # 2. Test Completed Customer (SLA Met, No Pending Items)
    # -------------------------------------------------------------
    print("\n--- 2. COMPLETED CUSTOMER (SLA MET, READY) ---")
    comp_email = f"comp_{uuid.uuid4().hex[:6]}@example.com"
    comp_res = create_customer_tool(db, CustomerCreate(
        name="Completed Customer",
        email=comp_email,
        phone="9876543210",
        customer_type="individual"
    ))
    comp_cid = uuid.UUID(comp_res["customer_id"])
    comp_cust = db.query(Customer).filter(Customer.id == comp_cid).first()
    comp_cust.status = "completed"

    comp_sid = f"sess-comp-{uuid.uuid4().hex[:8]}"
    comp_state = OnboardingState(
        customer_id=comp_cid,
        session_id=comp_sid,
        current_step="complete",
        pending_items=[], # No pending items!
        collected_info={"name": "Completed Customer", "customer_type": "individual"}
    )
    db.add(comp_state)
    db.commit()

    # Trigger follow-up: MUST BE REJECTED with 400
    threw_expected_error = False
    try:
        asyncio.run(trigger_single_follow_up(session_id=comp_sid, db=db))
    except HTTPException as ex:
        print(f"Expected Exception Caught: HTTP {ex.status_code} - {ex.detail}")
        assert ex.status_code == 400
        assert "already completed" in ex.detail.lower()
        threw_expected_error = True

    assert threw_expected_error, "trigger_single_follow_up must reject completed sessions with 400!"
    print("[PASS] Successfully blocked follow-up on completed customer!")

    # -------------------------------------------------------------
    # 3. Test generate_follow_up_llm directly with empty pending_items
    # -------------------------------------------------------------
    print("\n--- 3. LLM PROMPT DIRECT SAFETY TEST ---")
    direct_msg = generate_follow_up_llm(
        customer_name="Completed Customer",
        customer_type="individual",
        pending_items=[],
        sla_status="met",
        remaining_hours=0.0
    )
    print(f"Direct LLM Result for empty pending items: \"{direct_msg}\"")
    assert "upload" not in direct_msg.lower() and "pending" not in direct_msg.lower()
    assert "complete" in direct_msg.lower() or "verified" in direct_msg.lower()
    print("[PASS] LLM prompt helper never claims documents are pending when empty!")

    # -------------------------------------------------------------
    # 4. Test Dashboard Output for Completed Customer
    # -------------------------------------------------------------
    print("\n--- 4. DASHBOARD QUEUE INTEGRITY ---")
    dash = asyncio.run(get_operational_dashboard(limit=20, db=db))
    comp_queue_item = next((q for q in dash["prioritized_queue"] if q["session_id"] == comp_sid), None)
    assert comp_queue_item is not None, "Completed customer should be listed in queue for audit"
    print("Completed Queue Item in Dashboard:")
    print(f"  SLA Status: {comp_queue_item['sla_status']}")
    print(f"  Current Step: {comp_queue_item['current_step']}")
    print(f"  Pending Items: {comp_queue_item['pending_items']}")
    assert comp_queue_item['sla_status'] == 'met'
    assert len(comp_queue_item['pending_items']) == 0
    print("[PASS] Dashboard queue accurately exposes SLA 'met' and empty pending items for frontend display!")

finally:
    db.close()

print("\n" + "=" * 80)
print("ALL REGRESSION TESTS PASSED (100% VERIFIED)!")
print("=" * 80)
