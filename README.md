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

## ✅ Assignment Requirement Coverage

Mapped directly against the "What You Need to Build" checklist from the assignment brief:

| Assignment Requirement | What FlowAI Delivers |
| :--- | :--- |
| Accept a new customer and create an onboarding plan based on customer type | Customer explicitly picks a tier (no default assumed); FlowAI dynamically generates the required-document checklist and SLA clock for that tier (Individual 24h, Startup 48h, Enterprise 72h). |
| Collect required information and documents conversationally | Single free-text intake (name + email + phone in one message) or step-by-step — both extract cleanly with regex-backed validation. |
| Validate completeness and basic consistency of submitted information | Malformed emails/phone numbers are rejected and re-prompted individually without discarding already-valid fields; documents are validated against their expected type and content, not just accepted on upload. |
| Trigger mock/internal APIs to create setup tasks or update customer status | On full verification, downstream tasks (`create_account`, `setup_config`, `send_email`, `billing_profile`) fire automatically and the customer status updates to completed. |
| Remember onboarding state across sessions and follow up on pending items | PostgreSQL-backed LangGraph checkpointing (`AsyncPostgresSaver`) keyed to the customer's email; individual and batch AI-generated follow-up nudges for stalled customers. |
| Escalate exceptions to a human with context and recommended next action | After 3 failed attempts on a document, an escalation ticket is created with the failure reason, an AI-recommended next action, and the **actual uploaded document** attached for inline review. |
| Provide a dashboard showing onboarding stage, blockers and completion status | Operations Dashboard shows every customer's current stage, pending documents, SLA status, and urgency score in real time. |
| **Bonus:** SLA tracking and intelligent prioritization | Mathematical urgency formula (𝒰) ranks Breached > At-Risk > On-Track > Met, with one-click batch follow-up. |

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

## 🧪 Evaluation & Testing Methodology

The system was evaluated across end-to-end customer journeys and automated regression suites against the core criteria:

### 1. Conversational Intake & Problem Decomposition
- Gave all details in one message (*"I'm Rahul, rahul@gmail.com, 9876543210"*) — extracted correctly in a single turn.
- Gave details one at a time — same extraction logic handled it identically.
- Fed a malformed email and a 7-digit phone number — each was rejected individually, the field was re-asked for on its own, and already-valid fields were never lost.
- **Outcome:** `PASS` — the same intake logic handles both messy, single-shot input and slow, step-by-step input without branching code paths.

### 2. Dynamic Tier Selection & State Management
- Confirmed a fresh session assigns no tier until the customer explicitly picks one.
- Confirmed the required-document checklist and SLA clock (24h / 48h / 72h) change based on the selected tier, and stay consistent after a page refresh or session resume — proving the tier is real backend state, not a frontend-only label.
- **Outcome:** `PASS`.

### 3. Document Handling & Tool Calling (per document type)
Each document type is checked against what actually matters for it, not a single generic rule:
- **PAN Card / Aadhaar (Address Proof):** Vision model confirms document type, then matches the extracted name against the customer's profile — since these are personal identity documents.
- **GST Certificate / Company Registration:** Validated against the document's own content (GSTIN, business/company name) — **deliberately not** matched against the customer's personal name, since these are business documents. Verified this holds even after changing the personal name mid-test, and that a wrong document (e.g. a GST invoice submitted for a PAN request) is correctly rejected with a specific reason.
- **Outcome:** `PASS` — tool calling (Groq Vision) is applied with document-specific logic, not a one-size-fits-all check.

### 4. Human-in-the-Loop Design Under Stress
- Deliberately failed a document 3 times in a row — confirmed the agent stops retrying (no infinite loop) and creates an escalation ticket automatically.
- Confirmed the **actual failing document is persisted to the database** at the 3rd strike, so the operator opening the ticket sees the real uploaded file, not just a text summary of the failure.
- Tested all three operator decisions:
  - **Approve** — attempt counter resets, document marked verified, customer flow advances to the next document (no re-prompt loop).
  - **Request re-upload** — customer receives the operator's custom note and gets a fresh attempt.
  - **Reject** — customer session is permanently locked, all further `/chat` and `/document` calls return `HTTP 403`.
- **Outcome:** `PASS` — the escalation path always carries enough context (document + reason + recommendation) for a human to act without going back to the customer first.

### 5. Reliability & Orchestration
- Session resumption by email restores exact conversation history and document state after a full browser close, including mid-flow abandonment.
- Refreshing the page mid-session leaves tier, document progress, and chat state untouched.
- Injected deliberate DB failures — confirmed exponential backoff + jitter and automatic recovery.
- Hammered protected endpoints — confirmed `HTTP 429` with `Retry-After` once the rate limit is hit, while `/health` stays reachable throughout.
- **Outcome:** `PASS` — the graph's cyclic design (rather than a linear chain) is what makes drop-offs, retries, and human intervention survivable without special-casing each one.

---

## 🤖 AI Usage Note

*In accordance with the UnleashX assignment guidelines, this section outlines the explicit division between AI assistance and manual engineering decisions:*

### 1. Where AI Accelerated Delivery
- **UI & Frontend Development:** The entire single-page application (Customer Chat Portal + Operations & SLA Dashboard) was designed and built with the help of AI using React 18 and Tailwind CSS. This allowed rapid UI scaffolding and visual iteration, freeing up my focus for the core backend state machine, database design, and API resilience.
- **Boilerplate & Schema Generation:** AI was used to rapidly generate initial FastAPI endpoint definitions, Pydantic validation schemas, and database model boilerplates.
- **Multimodal Prompt Iteration:** Explored prompt variants for Groq vision models to ensure strict JSON schemas containing document type, extracted name, resolution checks, and failure reasons.
- **Technical Report Assembly:** Used AI to help compare and organize content while assembling the accompanying technical report — pulling architecture notes, engineering decisions, and evaluation results into one coherent document — and to generate the LaTeX used to typeset the final PDF.
- **Synthetic Test Generation:** Scripted mock payloads and test fixtures for simulating edge-case client requests in the automated test suite.

### 2. What I Architected & Decided Myself
- **Cyclic LangGraph State Machine:** Designed a stateful graph using the `interrupt()` primitive for human and customer wait states rather than naive linear chains.
- **Session-First Persistence Architecture:** Tied persistent LangGraph checkpoints (`AsyncPostgresSaver`) to customer email identifiers, enabling friction-free multi-session resumption without manual session ID input.
- **Write-Consolidation Strategy:** Diagnosed the 2.4-second database latency bottleneck under serverless PostgreSQL and redesigned persistence to cache working turns in memory, writing to PostgreSQL only at critical milestones.
- **Mathematical Urgency Formula:** Formulated the SLA scoring equation (𝒰) that dynamically weights overdue time and percentage thresholds to prioritize operations queues.
- **Tri-State Operational Protocol:** Engineered the 3 explicit operator choices (Approve, Re-upload, Reject) and enforced the corresponding HTTP 403 security boundary.

### 3. What AI-Generated Output I Rejected or Corrected
- **Rejected Infinite Retry Loops:** Default AI suggestions relied on continuous conversational prompting for invalid uploads. I rejected this pattern and enforced a strict 3-strike deterministic interrupt to prevent token bleeding.
- **Corrected Re-Verification Loops on Approval:** Default agent logic re-requested approved documents upon session resume. I wrote state short-circuiting logic to advance the internal document pointer immediately once an operator approves.
- **Eliminated Synchronous DB Calls:** Refactored AI-suggested synchronous tool calls inside agent nodes into non-blocking async pooled sessions with TCP keepalives to prevent serverless connection drops.

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
│   ├── images/
│   └── project_report.tex
├── scratch/
├── report.tex
├── requirements.txt
├── Dockerfile
├── .gitignore
└── README.md
```

---

## 📜 License
Developed for the UnleashX Production Assignment.
