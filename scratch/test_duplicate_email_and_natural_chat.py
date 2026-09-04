import sys, time
sys.path.insert(0, "backend")

from fastapi.testclient import TestClient
from main import app

print("=" * 80)
print("TEST: IMMEDIATE DUPLICATE EMAIL CHECK, NATURAL PROMPTS & DOCUMENT VERIFICATION")
print("=" * 80)

with TestClient(app) as client:
    # 1. Start onboarding
    resp_start = client.post("/onboarding/start?customer_type=individual")
    assert resp_start.status_code == 200
    start_data = resp_start.json()
    sid = start_data["session_id"]
    greeting = start_data["response"].encode('ascii', 'replace').decode('ascii')
    print(f"\n1. GREETING:\n{greeting}")
    assert "feel free to send them all at once or one by one" in greeting.lower()

    # 2. Provide Name
    resp_name = client.post(f"/onboarding/chat?session_id={sid}&message=Sayyed+Sabir+Ali")
    assert resp_name.status_code == 200
    name_reply = resp_name.json()["response"].encode('ascii', 'replace').decode('ascii')
    print(f"\n2. AFTER NAME:\n{name_reply}")
    assert "Sayyed Sabir Ali" in name_reply
    assert "email" in name_reply.lower()

    # 3. Test Immediate Duplicate Email Rejection
    print("\n3. TESTING IMMEDIATE DUPLICATE EMAIL REJECTION:")
    resp_dup = client.post(f"/onboarding/chat?session_id={sid}&message=sabirali969091@gmail.com")
    assert resp_dup.status_code == 200
    dup_reply = resp_dup.json()["response"].encode('ascii', 'replace').decode('ascii')
    print(f"Agent response on duplicate email:\n{dup_reply}")
    assert "already exists" in dup_reply.lower(), "Should immediately notify that email already exists!"
    assert "phone" not in dup_reply.lower(), "Should NOT ask for phone when email is duplicate!"
    print("[PASS] Duplicate email rejected immediately before asking for phone number!")

    # 4. User corrects with a fresh, unregistered email
    fresh_email = f"sabir_fresh_{int(time.time())}@example.com"
    print(f"\n4. PROVIDING FRESH EMAIL: {fresh_email}")
    resp_fresh = client.post(f"/onboarding/chat?session_id={sid}&message={fresh_email}")
    assert resp_fresh.status_code == 200
    fresh_reply = resp_fresh.json()["response"].encode('ascii', 'replace').decode('ascii')
    print(f"Agent response on fresh email:\n{fresh_reply}")
    assert "phone" in fresh_reply.lower(), "Should now ask for phone number!"
    print("[PASS] Fresh email accepted, prompted for phone number!")

    # 5. Provide 10-digit Phone Number (Completes registration)
    print("\n5. PROVIDING PHONE NUMBER: 7894561230")
    resp_phone = client.post(f"/onboarding/chat?session_id={sid}&message=7894561230")
    assert resp_phone.status_code == 200
    pdata = resp_phone.json()
    phone_reply = pdata["response"].encode('ascii', 'replace').decode('ascii')
    print(f"Agent response on phone completion:\n{phone_reply}")
    print(f"Customer ID:  {pdata.get('customer_id')}")
    print(f"Current Step: {pdata.get('current_step')}")
    assert pdata.get("customer_id") is not None, "Customer ID must be created in DB!"
    assert pdata.get("current_step") == "collect_docs", "Must transition directly to collect_docs!"
    print("[PASS] Customer created and transitioned to collect_docs cleanly!")

    # 6. Upload PAN Card Document (Ensure NO 'Session not found' error!)
    print("\n6. TESTING DOCUMENT UPLOAD ON NEW SESSION:")
    valid_pan_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Title (INCOME TAX DEPARTMENT GOVT OF INDIA)\n"
        b"/Author (Sayyed Sabir Ali)\n"
        b"/Subject (Permanent Account Number Card ABCDE1234F)\n"
        b">>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n" + (b"0" * 200)
    )
    resp_doc = client.post(
        f"/onboarding/document?session_id={sid}&document_type=pan_card",
        files={"file": ("pancard.pdf", valid_pan_pdf, "application/pdf")}
    )
    print(f"Document Upload Status: {resp_doc.status_code}")
    doc_json = resp_doc.json()
    print(f"Document Upload Result: {doc_json}")
    assert resp_doc.status_code == 200, f"Expected 200 OK, got {resp_doc.status_code}: {doc_json}"
    assert doc_json.get("success") is True
    print("[PASS] Document uploaded and verified successfully without 'Session not found' error!")

print("\n" + "=" * 80)
print("ALL CHECKS PASSED: DUPLICATE EMAIL REJECTED IMMEDIATELY & NO SESSION ERROR!")
print("=" * 80)
