"""
LangSmith Connection and Tracing Verification Script.
Run this script to verify your LangSmith API Key and project setup.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv()

import langsmith

print("=" * 60)
print("[CHECK] LangSmith Configuration Check")
print("=" * 60)

tracing_v2 = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
api_key = os.getenv("LANGCHAIN_API_KEY", "")
project = os.getenv("LANGCHAIN_PROJECT", "flowai-onboarding")
endpoint = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")

print(f"- Tracing V2 Enabled : {tracing_v2}")
print(f"- Project Name       : {project}")
print(f"- Endpoint           : {endpoint}")
print(f"- API Key Configured : {'Yes (' + api_key[:8] + '...' + api_key[-4:] + ')' if api_key else 'No (Missing)'}")

if not api_key or api_key.strip() == "":
    print("\n[NOTE] LANGCHAIN_API_KEY is not yet configured in .env.")
    print("To enable full observability in your LangSmith dashboard:")
    print("   1. Sign up for free at: https://smith.langchain.com/")
    print("   2. Generate an API Key under Settings -> API Keys.")
    print("   3. Add to your .env file:")
    print("      LANGCHAIN_TRACING_V2=true")
    print("      LANGCHAIN_API_KEY=lsv2_pt_...")
    print("      LANGCHAIN_PROJECT=flowai-onboarding")
    sys.exit(0)

try:
    client = langsmith.Client(api_key=api_key, api_url=endpoint)
    projects = list(client.list_projects(reference_dataset_name=None))
    print(f"\n[OK] Successfully authenticated with LangSmith!")
    print(f"- Active Projects found: {len(projects)}")
    print(f"- FlowAI traces will stream to project: '{project}'")
except Exception as e:
    print(f"\n[ERROR] Error connecting to LangSmith: {e}")
    sys.exit(1)
