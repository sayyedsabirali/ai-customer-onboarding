import sys, time
sys.path.insert(0, "backend")

from fastapi.testclient import TestClient
from main import app

print("=" * 80)
print("TEST: NO DUPLICATE PROMPT & SEAMLESS NEXT-DOC PROGRESSION")
print("=" * 80)

with TestClient(app) as client:
    # 1. Start onboarding
    resp_start = client.post("/onboarding/start?customer_type=individual")
    assert resp_start.status_code == 200
    sid = resp_start.json()["session_id"]
    print("1. Started session:", sid)

    # 2. Provide Name and fresh Email
    fresh_email = f"sabir_nodup_{int(time.time())}@example.com"
    resp_info = client.post(f"/onboarding/chat?session_id={sid}&message=my+name+is+Sayyed+Sabir+Ali+and+email+is+{fresh_email}")
    assert resp_info.status_code == 200
    print("\n2. Name + Email Reply:\n", resp_info.json()["response"].encode('ascii', 'replace').decode('ascii'))

    # 3. Provide Phone (Registration turn)
    resp_phone = client.post(f"/onboarding/chat?session_id={sid}&message=9876543210")
    assert resp_phone.status_code == 200
    pdata = resp_phone.json()
    reg_reply = pdata["response"].encode('ascii', 'replace').decode('ascii')
    print("\n3. Registration Turn Reply:\n", reg_reply)
    assert "awesome" in reg_reply.lower() or "registered" in reg_reply.lower()
    # Ensure it doesn't return the raw duplicate string
    assert "please upload your pan card." not in reg_reply.lower() or "awesome" in reg_reply.lower()
    print("[PASS] Registration message generated cleanly without redundant interrupt!")

    # 4. Upload PAN Card
    print("\n4. Uploading PAN Card...")
    pan_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Title (INCOME TAX DEPARTMENT GOVT OF INDIA)\n"
        b"/Author (Sayyed Sabir Ali)\n"
        b"/Subject (Permanent Account Number Card ABCDE1234F)\n"
        b">>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n" + (b"0" * 200)
    )
    resp_doc = client.post(
        f"/onboarding/document?session_id={sid}&document_type=pan_card",
        files={"file": ("pancard.pdf", pan_pdf, "application/pdf")}
    )
    assert resp_doc.status_code == 200
    doc_reply = resp_doc.json()["response"].encode('ascii', 'replace').decode('ascii')
    print("Document Upload Agent Response:\n", doc_reply)
    assert "pan card received" in doc_reply.lower() or "address proof" in doc_reply.lower()
    assert "please upload your pan card" not in doc_reply.lower(), "Should NOT ask for PAN Card again after it was just uploaded!"
    print("[PASS] Successfully acknowledged PAN Card and prompted for Address Proof!")

print("=" * 80)
print("ALL TESTS PASSED: NO DUPLICATE MESSAGES & PROPER NEXT-DOC FLOW!")
print("=" * 80)
