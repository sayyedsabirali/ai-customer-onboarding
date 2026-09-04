"""
Test script to simulate a multi-turn conversation belonging to ONE session,
verifying that LangSmith groups them under a single thread.
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import asyncio
from uuid import uuid4
from agent.graph import build_onboarding_graph
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

async def run_multi_turn_session():
    checkpointer = MemorySaver()
    graph = build_onboarding_graph(checkpointer)

    session_id = str(uuid4())
    print(f"[*] Starting new multi-turn session: {session_id[:8]}...")

    # Turn 1: Start
    config_turn1 = {
        "configurable": {"thread_id": session_id},
        "tags": [f"session:{session_id[:8]}", "flowai-onboarding"],
        "metadata": {
            "thread_id": session_id,
            "session_id": session_id,
            "customer_type": "startup"
        },
        "run_name": f"Session [{session_id[:8]}] - Start"
    }
    from agent.state import initialize_state
    init_payload = initialize_state(customer_id=None, session_id=session_id, message="", customer_type="startup")
    print("Turn 1: Initializing onboarding...")
    res1 = await graph.ainvoke(init_payload, config=config_turn1)
    print("Turn 1 complete.")

    # Turn 2: Send Profile details
    config_turn2 = {
        "configurable": {"thread_id": session_id},
        "tags": [f"session:{session_id[:8]}", "flowai-onboarding"],
        "metadata": {
            "thread_id": session_id,
            "session_id": session_id,
            "turn": 2
        },
        "run_name": f"Session [{session_id[:8]}] - Intake"
    }
    print("Turn 2: Customer sending name and contact...")
    res2 = await graph.ainvoke(Command(resume="My name is Sarah Connor, email sarah@skynet.com, phone 9876543210"), config=config_turn2)
    print("Turn 2 complete.")

    print(f"\n[OK] Both turns executed for thread_id: {session_id}")
    print(f"[NOTE] In LangSmith (https://smith.langchain.com/):")
    print(f"       Click on the 'Threads' tab inside 'flowai-onboarding' project.")
    print(f"       You will see session '{session_id[:8]}' grouped as a SINGLE cohesive thread!")

if __name__ == "__main__":
    asyncio.run(run_multi_turn_session())
