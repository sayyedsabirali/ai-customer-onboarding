import sys, io, time, json
sys.path.insert(0, "backend")

from fastapi.testclient import TestClient
from main import app
from agent.config import normalize_document_type

print("=" * 80)
print("TEST: TAX_ID ALIAS & SPEED VERIFICATION")
print("=" * 80)

# 1. Verify normalize_document_type alias
norm_tax = normalize_document_type("tax_id")
norm_pan = normalize_document_type("pan_card")
norm_biz = normalize_document_type("business_reg")
print(f"normalize_document_type('tax_id')       -> '{norm_tax}' (Expected: 'pan_card')")
print(f"normalize_document_type('pan_card')     -> '{norm_pan}' (Expected: 'pan_card')")
print(f"normalize_document_type('business_reg') -> '{norm_biz}' (Expected: 'company_registration')")

assert norm_tax == "pan_card", f"Expected pan_card, got {norm_tax}"
assert norm_biz == "company_registration"
print("[PASS] Alias mapping for tax_id and business_reg verified!")

# 2. Test live server start & chat latency
with TestClient(app) as client:
    # Measure /start
    t0 = time.time()
    resp_start = client.post("/onboarding/start?customer_type=individual")
    dt_start = round((time.time() - t0) * 1000, 1)
    sdata = resp_start.json()
    sid = sdata.get("session_id")
    print(f"\nPOST /start Latency: {dt_start}ms | session_id: {sid}")
    assert resp_start.status_code == 200

    # Measure /chat (Provide Name)
    t0 = time.time()
    resp_chat = client.post(f"/onboarding/chat?session_id={sid}&message=Sayyed+Sabir+Ali")
    dt_chat1 = round((time.time() - t0) * 1000, 1)
    print(f"POST /chat (Name) Latency: {dt_chat1}ms | Response: {resp_chat.json().get('response')[:50]}...")
    assert resp_chat.status_code == 200

    # Measure /chat (Provide Email)
    unique_email = f"speedtest_{int(time.time())}@example.com"
    t0 = time.time()
    resp_chat2 = client.post(f"/onboarding/chat?session_id={sid}&message={unique_email}")
    dt_chat2 = round((time.time() - t0) * 1000, 1)
    print(f"POST /chat (Email) Latency: {dt_chat2}ms | Response: {resp_chat2.json().get('response')[:50]}...")
    assert resp_chat2.status_code == 200

    # Measure /chat (Provide Phone)
    t0 = time.time()
    resp_chat3 = client.post(f"/onboarding/chat?session_id={sid}&message=9876543210")
    dt_chat3 = round((time.time() - t0) * 1000, 1)
    print(f"POST /chat (Phone) Latency: {dt_chat3}ms | Response: {resp_chat3.json().get('response')[:50]}...")
    assert resp_chat3.status_code == 200

    # Measure /chat (Provide Type - triggers customer registration & clean interrupt!)
    t0 = time.time()
    resp_chat4 = client.post(f"/onboarding/chat?session_id={sid}&message=individual")
    dt_chat4 = round((time.time() - t0) * 1000, 1)
    c4 = resp_chat4.json()
    print(f"POST /chat (Tier -> Customer Created!) Latency: {dt_chat4}ms")
    print(f"Customer ID: {c4.get('customer_id')}")
    print(f"Step: {c4.get('current_step')}")
    clean_resp = c4.get('response', '')[:60].encode('ascii', 'replace').decode('ascii')
    print(f"Response: {clean_resp}...")
    assert resp_chat4.status_code == 200
    assert c4.get("customer_id") is not None
    assert c4.get("current_step") == "collect_docs"

    # Test Document Upload with document_type='tax_id'
    dummy_pdf = b"%PDF-1.4 PAN CARD GOVT OF INDIA Permanent Account Number ABCDE1234F Name: Sayyed Sabir Ali"
    t0 = time.time()
    resp_doc = client.post(
        f"/onboarding/document?session_id={sid}&document_type=tax_id",
        files={"file": ("pancard.pdf", dummy_pdf, "application/pdf")}
    )
    dt_doc = round((time.time() - t0) * 1000, 1)
    print(f"\nPOST /document (type='tax_id') Latency: {dt_doc}ms | Status: {resp_doc.status_code}")
    print(f"Document upload response: {resp_doc.json()}")
    assert resp_doc.status_code == 200, f"Expected 200 OK for tax_id upload, got {resp_doc.status_code}: {resp_doc.text}"

print("\n" + "=" * 80)
print("VERIFICATION COMPLETE: Speed optimized and tax_id upload accepted cleanly!")
print("=" * 80)
