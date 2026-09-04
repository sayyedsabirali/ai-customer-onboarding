import sys, time
sys.path.insert(0, "backend")

from fastapi.testclient import TestClient
from main import app

print("=" * 80)
print("TEST: CUSTOMER TIER PREFILL & CONVERSATION CONTINUITY")
print("=" * 80)

with TestClient(app) as client:
    # 1. Start with customer_type=individual
    resp_start = client.post("/onboarding/start?customer_type=individual")
    assert resp_start.status_code == 200
    start_data = resp_start.json()
    sid = start_data["session_id"]
    greeting = start_data["response"]
    clean_greeting = greeting.encode('ascii', 'replace').decode('ascii')
    print(f"1. Greeting: {clean_greeting}")
    assert "Individual" in greeting, "Greeting should acknowledge Individual account tier"

    # 2. Provide Name
    resp_name = client.post(f"/onboarding/chat?session_id={sid}&message=Sayyed+Sabir+Ali")
    assert resp_name.status_code == 200
    print(f"\n2. After Name: {resp_name.json()['response']}")
    assert "email" in resp_name.json()["response"].lower()

    # 3. Provide Email
    unique_email = f"sabir_prefill_{int(time.time())}@example.com"
    resp_email = client.post(f"/onboarding/chat?session_id={sid}&message={unique_email}")
    assert resp_email.status_code == 200
    print(f"\n3. After Email: {resp_email.json()['response']}")
    assert "phone" in resp_email.json()["response"].lower()

    # 4. Provide Phone
    # Since customer_type='individual' was already selected, this should COMPLETE info collection!
    resp_phone = client.post(f"/onboarding/chat?session_id={sid}&message=9876543210")
    assert resp_phone.status_code == 200
    phone_data = resp_phone.json()
    clean_resp = phone_data['response'].encode('ascii', 'replace').decode('ascii')
    print(f"\n4. After Phone: {clean_resp}")
    print(f"   Current Step: {phone_data.get('current_step')}")
    print(f"   Customer ID:  {phone_data.get('customer_id')}")

    # VERIFY IT DID NOT ASK FOR TIER AGAIN!
    assert "individual, startup, or enterprise" not in phone_data['response'].lower(), "Agent should NOT re-ask for customer tier!"
    assert phone_data.get("current_step") == "collect_docs", "Step should automatically transition to collect_docs!"
    assert phone_data.get("customer_id") is not None, "Customer should be created in DB!"

print("\n" + "=" * 80)
print("SUCCESS: Tier was seamlessly recognized and NOT asked again!")
print("=" * 80)
