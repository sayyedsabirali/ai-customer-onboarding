# FlowAI — Autonomous AI Customer Onboarding & SLA Intelligence Agent
> **UnleashX Production Engineering Assignment**
> An autonomous, production-grade AI onboarding platform built with **LangGraph**, **PostgreSQL Checkpointing**, **Groq Multimodal Vision OCR**, and **Real-Time Operations SLA Intelligence**.

[![Live App](https://img.shields.io/badge/Live%20Deployment-Render-46E3B7.svg?style=flat-square&logo=render)](https://ai-customer-onboarding.onrender.com/)
[![Project Report](https://img.shields.io/badge/Project%20Report-Google%20Drive-4285F4.svg?style=flat-square&logo=google-drive)](https://drive.google.com/file/d/1g1IDDEbF4GM9_TPVz2wf1ofbnO30IgWL/view?usp=sharing)
[![GitHub Repo](https://img.shields.io/badge/GitHub-Repository-181717.svg?style=flat-square&logo=github)](https://github.com/sayyedsabirali/ai-customer-onboarding)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-FF6F00.svg?style=flat-square)](https://langchain-ai.github.io/langgraph/)
[![Groq Vision](https://img.shields.io/badge/Vision%20%26%20LLM-Groq%20Cloud-f55036.svg?style=flat-square)](https://groq.com/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL%20(Neon)-336791.svg?style=flat-square&logo=postgresql)](https://neon.tech/)
[![React 18](https://img.shields.io/badge/Frontend-React%2018%20%2B%20Tailwind-61DAFB.svg?style=flat-square&logo=react)](https://reactjs.org/)
[![Bonus Challenge](https://img.shields.io/badge/Bonus-SLA%20Tracking%20%26%20Prioritization-success?style=flat-square)](#bonus-challenge--sla-intelligence-engine)

---

### 📌 Project Deliverables & Live Links

| Deliverable | Destination / Resource | Notes |
| :--- | :--- | :--- |
| 🌐 **Live Deployed Application** | **[https://ai-customer-onboarding.onrender.com/](https://ai-customer-onboarding.onrender.com/)** | Customer Portal + Ops SLA Dashboard |
| 📑 **Project & Architecture Report** | **[Google Drive Document (PDF)](https://drive.google.com/file/d/1g1IDDEbF4GM9_TPVz2wf1ofbnO30IgWL/view?usp=sharing)** | In-depth system design & evaluation paper |
| 💻 **Source Code Repository** | **[sayyedsabirali/ai-customer-onboarding](https://github.com/sayyedsabirali/ai-customer-onboarding)** | Clean production code & test suites |
| 📊 **Live Swagger API Docs** | **[API Documentation (/docs)](https://ai-customer-onboarding.onrender.com/docs)** | Interactive OpenAPI test console |

---

## 💡 Executive Summary

**FlowAI** is an autonomous AI customer onboarding system engineered to replace slow manual verification workflows and eliminate SLA breaches:
- **Conversational Intake:** Collects name, email, phone, and tier conversationally without rigid multi-step forms.
- **Multimodal Vision OCR:** Powered by Groq Cloud (`llama-3.2-11b-vision-preview`) to parse identity/business documents, extract metadata, and validate name consistency in seconds.
- **Stateful Resumption:** Backed by PostgreSQL LangGraph checkpointing (`AsyncPostgresSaver`) keyed to customer emails, preserving complete chat and document progress across reloads and disconnects.
- **Deterministic HITL Escalation:** Enforces a 3-strike validation policy; failing uploads trigger an escalation ticket preserving the actual uploaded file for inline operator review.
- **Real-Time SLA Intelligence:** Monitors tier-specific deadlines (Individual 24h, Startup 48h, Enterprise 72h) with dynamic urgency scoring and one-click batch follow-ups.

---

## ✅ Assignment Capabilities Checklist

| Feature Requirement | Implementation | Status |
| :--- | :--- | :---: |
| **Tier-Based Onboarding Plan** | Dynamic checklists & SLA deadlines (Individual 24h, Startup 48h, Enterprise 72h). | ✅ Met |
| **Conversational Intake** | Single-shot or multi-turn extraction with regex-backed field validation. | ✅ Met |
| **Document OCR & Consistency** | Groq Vision (`llama-3.2-11b-vision-preview`) extracts metadata and cross-checks names. | ✅ Met |
| **Internal & Mock Integrations** | Auto-provisions accounts, configuration tasks, and notifications on completion. | ✅ Met |
| **Stateful Persistence** | PostgreSQL `AsyncPostgresSaver` keyed by email; restores exact conversation state. | ✅ Met |
| **HITL Exception Escalation** | 3-strike policy routes failing files to operators with inline preview and Tri-State actions. | ✅ Met |
| **Operations SLA Dashboard** | Real-time Kanban-style queue with dynamic urgency scoring (𝒰) and batch follow-ups. | ✅ Met |

---

## 📸 Visual Walkthrough & Core Features

### 1. Conversational Customer Onboarding Portal
Natural dialogue flow that extracts profile metadata, enforces plan requirements, and renders in-chat document upload cards.
![Customer Onboarding Portal](docs/images/customer_chat_portal.png)

### 2. Operations & SLA Intelligence Dashboard
Live view of all onboarding accounts prioritized dynamically by urgency score. Highlights breached and at-risk deadlines with real-time KPI metrics.
![Operations & SLA Intelligence Dashboard](docs/images/operations_sla_dashboard.png)

### 3. Human-in-the-Loop Support Escalation
Automated routing after 3 failed upload attempts. Operators inspect documents inline (PDF/images) and execute Tri-State actions (**Approve**, **Re-upload**, or **Reject Application**).

| Escalation Tickets Queue | Inspection & Decision Modal |
| :---: | :---: |
| ![Support Tickets](docs/images/human_escalation_tickets.png) | ![Review Modal](docs/images/human_escalation_modal.png) |

### 4. Multi-Select Batch Proactive Follow-Up
Operators select multiple stalled customers to dispatch context-aware, personalized LLM reminder nudges in a single click.
![Batch Follow-up Workflow](docs/images/batch_followup_feature.png)

---

## 🏗️ System Architecture — How a Request Actually Flows

![System Architecture Diagram](docs/images/architecture_diagram.png)

1. **Frontend (React SPA):** Dual interfaces — Customer Chat & Document Upload Portal, and Operations SLA Intelligence Dashboard.
2. **FastAPI Gateway:** Enforces rate limiting (`60 req/min`), structured request logging, and dispatches requests to the agent graph.
3. **Cyclic LangGraph Workflow:**
   - `Tier Selection` → `Metadata Extraction` → `Document Verification Loop`.
   - Routes uploads to **Groq Multimodal Vision** for live OCR parsing.
   - Enforces a 3-strike threshold: after 3 failed attempts, routes immediately to Human Review.
   - On full verification, executes provisioning (`account`, `config`, `billing`) and transitions to `Completed`.
4. **Human-in-the-Loop (HITL):** Persists failed files to the database for inline operator review. Operators can **Approve** (advances pointer), **Re-upload** (prompts customer), or **Reject** (locks session with HTTP 403).
5. **Persistence & Storage (Neon PostgreSQL):** Backed by `AsyncPostgresSaver` connection pooling, persisting checkpoints at milestone events for instant session resumption.

---

## ⚡ Core Production Engineering Decisions & Trade-Offs

### 1. Eliminating Chat Lag with Write-Consolidation
- **The Problem:** Writing every conversational turn and validation attempt to serverless PostgreSQL (Neon) caused 1.5–2.5s latency per message.
- **The Solution:** Session working state is cached in LangGraph thread memory. PostgreSQL writes are deferred until critical milestones:
  1. An attempt fails (tracking escalation quotas).
  2. The 3rd attempt is reached (persisting the escalation ticket + the failing document).
  3. A document is verified (persisting clean resume state).
- **The Result:** Cut message turnaround latency by **~60%** (from ~2.4s to <850ms).

### 2. Resilient Database Pooling (Neon Serverless TCP Keepalives)
- **The Problem:** Cloud database poolers silently drop idle TCP sockets after 60–120s, throwing `server closed the connection unexpectedly`.
- **The Solution:** Configured `pool_recycle=60`, `pool_pre_ping=True`, and OS-level TCP keepalives (`keepalives_idle=30`, `keepalives_interval=10`, `keepalives_count=5`).
- **The Result:** 100% connection stability during long idle periods and overnight runs.

### 3. Human Approval Short-Circuiting
- **The Problem:** In standard agents, when a human reviewer approves a document, resuming the graph can re-trigger the document prompt asking the user for the same file again.
- **The Solution:** State synchronization logic detects reviewer approvals, updates the verified list, advances the internal pointer, and prompts for the *next* document upon resume.

### 4. Mathematical Urgency Scoring (Bonus Challenge)
- **The Formula:**
  - Individual: 24h | Startup: 48h | Enterprise: 72h limit.
  - $\text{Breached}: \Delta t \le 0 \implies \mathcal{U} = 1000 + (\text{Overdue Hours} \times 10)$
  - $\text{At-Risk}: 0 < T_{\text{rem}} \le 25\% \implies \mathcal{U} = 500 + \text{SLA Used \%}$
  - $\text{On-Track}: T_{\text{rem}} > 25\% \implies \mathcal{U} = 100 + \text{SLA Used \%}$
- **The Result:** Critical drop-offs immediately bubble to the top of the operations queue.

---

## 🧪 Evaluation & Test Coverage Matrix

The platform was evaluated against 5 critical production vectors using end-to-end user simulations and automated regression suites:

| Evaluation Vector | Test Scenario | Verified Behavior | Status |
| :--- | :--- | :--- | :---: |
| **Conversational Intake** | Single-shot combined profile input vs multi-turn; malformed email/phone. | Extracts valid fields cleanly; re-prompts only invalid fields without data loss. | ✅ PASS |
| **Dynamic Tiering** | Individual (24h), Startup (48h), Enterprise (72h) selection and reloads. | Dynamically provisions checklist and SLA clock; state persists across sessions. | ✅ PASS |
| **Vision OCR Verification** | Personal ID (PAN/Aadhaar) vs Corporate docs (GST/Registration). | Personal docs cross-match name; corporate docs validate entity number independently. | ✅ PASS |
| **HITL Escalation Loop** | 3 consecutive upload failures; operator Approve / Re-upload / Reject. | Halts retries at 3rd strike, preserves file for inline review; override advances flow. | ✅ PASS |
| **Fault Resilience & Scale** | Dropped DB connections, rapid session reloads, and rate-limit hammering. | Auto-reconnects via TCP keepalives; enforces HTTP 429 while keeping `/health` live. | ✅ PASS |

---

## 🤖 AI Usage Note

*In accordance with UnleashX guidelines, here is the breakdown between AI acceleration and human engineering decisions:*

### 1. What AI Accelerated
- **UI Prototyping:** Scaffolding the React 18 / Tailwind single-page application (Customer Chat & Ops SLA Dashboard).
- **Schema & Boilerplate:** Generating initial FastAPI Pydantic request/response models and DB tables.
- **OCR Prompt Tuning:** Iterating Groq LLaVA / Llama-3.2 vision system prompts for structured JSON extraction.
- **Mock Test Fixtures:** Generating synthetic test payloads for regression scripts in `scratch/`.

### 2. What I Architected & Decided Myself
- **Cyclic LangGraph Architecture:** Stateful graph using interrupt primitives rather than rigid linear chains.
- **Session-First Persistence:** Keyed LangGraph checkpoints (`AsyncPostgresSaver`) to emails for zero-friction resume.
- **Write-Consolidation Strategy:** Eliminated 2.4s chat lag by caching working turns and committing DB writes at milestones.
- **Mathematical Urgency Formula:** Designed the SLA scoring formula (𝒰) to dynamically bubble up at-risk accounts.
- **Tri-State Operator Security Boundary:** Built the Approve, Re-upload, Reject protocol with HTTP 403 locking.

### 3. What AI-Generated Output I Rejected or Corrected
- **Rejected Infinite Chat Loops:** Discarded naive LLM re-prompting on failures; enforced strict 3-strike deterministic escalation.
- **Fixed Document Re-prompt Bug:** Overrode agent memory upon human approval so it advances rather than re-requesting verified files.
- **Removed Sync Database Blocking:** Refactored synchronous DB tool calls to async pooled connections with TCP keepalives.

---

## 🚀 Quickstart & Setup Guide

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/sayyedsabirali/ai-customer-onboarding.git
cd ai-customer-onboarding

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Create a `.env` file in the root directory:
```env
DATABASE_URL="postgresql://<username>:<password>@<host>:<port>/<dbname>?sslmode=require"
GROQ_API_KEY="your_groq_api_key_here"
PORT=8000
```

### 3. Run the Application
```bash
python backend/main.py
```
Server starts on `http://localhost:8000`.

### 4. Access the Application
- **Live Production URL:** [https://ai-customer-onboarding.onrender.com/](https://ai-customer-onboarding.onrender.com/)
- **Live Swagger API Docs:** [https://ai-customer-onboarding.onrender.com/docs](https://ai-customer-onboarding.onrender.com/docs)
- **Live Health Check Endpoint:** [https://ai-customer-onboarding.onrender.com/health](https://ai-customer-onboarding.onrender.com/health)
- **Local Development URL:** `http://localhost:8000/`
- **Local Swagger Docs:** `http://localhost:8000/docs`

---

## 📁 Project Structure

```
ai-customer-onboarding/
├── backend/
│   ├── agent/
│   │   ├── config.py
│   │   ├── graph.py
│   │   ├── nodes.py
│   │   ├── state.py
│   │   └── tools.py
│   ├── database/
│   │   ├── connection.py
│   │   └── models.py
│   ├── routes/
│   │   ├── escalation.py
│   │   └── onboarding.py
│   ├── utils/
│   │   ├── logger.py
│   │   ├── rate_limiter.py
│   │   └── resilience.py
│   └── main.py
├── frontend/
│   └── index.html
├── docs/
│   ├── architecture.mmd
│   └── images/
├── scratch/
├── requirements.txt
├── Dockerfile
├── .gitignore
└── README.md
```

---

## 📜 License
Developed for the UnleashX Production Assignment.
