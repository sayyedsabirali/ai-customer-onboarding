import sys, json
sys.path.insert(0, "backend")

from fastapi.testclient import TestClient
from main import app

print("=" * 80)
print("FRONTEND & BACKEND INTEGRATION TEST")
print("=" * 80)

with TestClient(app) as client:
    # 1. Test GET / (Browser requesting HTML)
    print("\n--- 1. TESTING GET / (CUSTOMER ONBOARDING PORTAL) ---")
    resp_root = client.get("/", headers={"Accept": "text/html,application/xhtml+xml"})
    print(f"GET / Status: {resp_root.status_code}")
    print(f"Content-Type: {resp_root.headers.get('content-type')}")
    assert resp_root.status_code == 200, f"Expected 200, got {resp_root.status_code}"
    assert "text/html" in resp_root.headers.get("content-type", "")
    assert "FlowAI" in resp_root.text
    assert "Customer Portal" in resp_root.text
    print("[PASS] Customer Portal HTML served successfully on GET /")

    # 2. Test GET /admin (Operations Dashboard)
    print("\n--- 2. TESTING GET /admin (OPERATIONS & SLA DASHBOARD) ---")
    resp_admin = client.get("/admin", headers={"Accept": "text/html,application/xhtml+xml"})
    print(f"GET /admin Status: {resp_admin.status_code}")
    assert resp_admin.status_code == 200, f"Expected 200, got {resp_admin.status_code}"
    assert "text/html" in resp_admin.headers.get("content-type", "")
    assert "Operations Intelligence Dashboard" in resp_admin.text
    print("[PASS] Operations Dashboard HTML served successfully on GET /admin")

    # 3. Test Static Files Mount
    print("\n--- 3. TESTING STATIC ASSET MOUNT (/static/index.html) ---")
    resp_static = client.get("/static/index.html")
    print(f"GET /static/index.html Status: {resp_static.status_code}")
    assert resp_static.status_code == 200
    print("[PASS] Static files mount operational!")

    # 4. Test API JSON Fallback on GET /
    print("\n--- 4. TESTING GET / WITH APPLICATION/JSON ACCEPT HEADER ---")
    resp_json = client.get("/", headers={"Accept": "application/json"})
    print(f"GET / (JSON) Status: {resp_json.status_code}")
    json_data = resp_json.json()
    print(f"Response: {json.dumps(json_data)}")
    assert json_data.get("service") == "AI Customer Onboarding Agent API"
    print("[PASS] JSON API status fallback operational for API clients!")

    # 5. Test Live API Endpoints (Health & Metrics)
    print("\n--- 5. VERIFYING CORE API ENDPOINTS REMAIN INTACT ---")
    health = client.get("/health").json()
    print(f"Health Status: {health.get('status')} | LLM: {health.get('llm_service', {}).get('provider')}")
    assert health.get("status") == "healthy"

    metrics = client.get("/metrics").json()
    print(f"Metrics: Total Customers = {metrics.get('metrics', {}).get('total_customers')}")
    assert "metrics" in metrics
    print("[PASS] Backend API contracts completely intact!")

    # 6. Test Frontend Start Onboarding Flow via API
    print("\n--- 6. VERIFYING ONBOARDING START FLOW ---")
    start_resp = client.post("/onboarding/start?customer_type=individual")
    start_data = start_resp.json()
    resp_preview = start_data.get('response', '')[:60].encode('ascii', 'replace').decode('ascii')
    print(f"Start Response:   {resp_preview}...")
    assert start_data.get("success") is True
    assert start_data.get("session_id") is not None
    print("[PASS] Onboarding start endpoint working with frontend session structure!")

print("\n" + "=" * 80)
print("ALL FRONTEND INTEGRATION TESTS PASSED SUCCESSFULLY!")
print("=" * 80)
