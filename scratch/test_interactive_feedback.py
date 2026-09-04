import sys, time
sys.path.insert(0, "backend")

from fastapi.testclient import TestClient
from main import app

print("=" * 80)
print("TEST: INTERACTIVE AGENT MESSAGING & FEEDBACK")
print("=" * 80)

with TestClient(app) as client:
    # 1. Start onboarding
    resp_start = client.post("/onboarding/start?customer_type=individual")
    assert resp_start.status_code == 200
    sid = resp_start.json()["session_id"]
    greeting = resp_start.json()["response"].encode('ascii', 'replace').decode('ascii')
    print(f"\n1. GREETING:\n{greeting}\n")

    # 2. Test: User provides name + invalid phone number
    # "my name is sayyed sabir ali and phone is 12345"
    print("2. TESTING NAME + INVALID PHONE (Should acknowledge name and flag invalid phone):")
    resp_mixed = client.post(f"/onboarding/chat?session_id={sid}&message=my+name+is+sayyed+sabir+ali+and+phone+is+12345")
    assert resp_mixed.status_code == 200
    mixed_reply = resp_mixed.json()["response"].encode('ascii', 'replace').decode('ascii')
    print(f"Agent reply:\n{mixed_reply}\n")
    assert "noted your name" in mixed_reply.lower() or "sayyed sabir ali" in mixed_reply.lower()
    assert "digits" in mixed_reply.lower() or "invalid" in mixed_reply.lower()
    print("[PASS] Successfully acknowledged name and politely flagged phone error!")

    # 3. Test: User provides valid email
    fresh_email = f"sabir_interactive_{int(time.time())}@example.com"
    print(f"3. TESTING EMAIL ADDITION ({fresh_email}):")
    resp_email = client.post(f"/onboarding/chat?session_id={sid}&message=my+email+is+{fresh_email}")
    assert resp_email.status_code == 200
    email_reply = resp_email.json()["response"].encode('ascii', 'replace').decode('ascii')
    print(f"Agent reply:\n{email_reply}\n")
    assert "sayyed sabir ali" in email_reply.lower() or "noted your email" in email_reply.lower()
    assert "phone" in email_reply.lower()
    print("[PASS] Personalized acknowledgment with name & email, asking for 10-digit phone!")

    # 4. Test: User provides 10-digit phone to complete registration
    print("4. TESTING REGISTRATION COMPLETION (7894561230):")
    resp_phone = client.post(f"/onboarding/chat?session_id={sid}&message=7894561230")
    assert resp_phone.status_code == 200
    phone_reply = resp_phone.json()["response"].encode('ascii', 'replace').decode('ascii')
    print(f"Agent reply:\n{phone_reply}\n")
    assert "registration details" in phone_reply.lower() or "profile" in phone_reply.lower()
    assert "pan card" in phone_reply.lower()
    print("[PASS] Rich, beautiful registration summary generated!")

print("=" * 80)
print("ALL INTERACTIVE MESSAGING CHECKS PASSED!")
print("=" * 80)
