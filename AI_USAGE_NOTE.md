# FlowAI — AI Usage Note & Engineering Decisions

> **UnleashX Production Engineering Assignment**  
> Transparent disclosure of AI acceleration, human architectural design, and rejected AI outputs.

---

## 💡 1. Approach to AI Acceleration

In line with UnleashX's stated principle (*"AI usage: strongly encouraged. We are testing how well you understand a real problem, use AI intelligently, and ship something that works"*), AI was utilized as an **advanced pair programmer and development accelerator**.

Rather than treating AI as an autonomous generator that outputs unchecked code, I used it to:
- Accelerate repetitive frontend scaffolding and boilerplate generation.
- Rapidly iterate on multimodal vision prompts and JSON schemas.
- Generate synthetic edge-case data fixtures for stress testing.

All core architectural decisions, state-machine transitions, database pooling strategies, and security barriers were designed and directed by me.

---

## ⚡ 2. Where AI Accelerated Delivery

1. **Frontend Single-Page Application (React 18 + Tailwind CSS):**
   - AI was used to scaffold the interactive Customer Chat Portal and the Operations & SLA Dashboard in `frontend/index.html`.
   - Rapidly built dynamic UI elements: interactive file upload cards inside the chat stream, real-time SLA countdown timers, urgency badges, and ticket resolution modals.
   - *Impact:* Cut frontend development time from ~16 hours to ~3 hours, allowing me to focus the majority of the assignment on backend resilience, LangGraph orchestration, and database persistence.

2. **API Schemas & Model Boilerplate:**
   - Generated initial FastAPI Pydantic request/response schemas (`OnboardingRequest`, `DocumentUploadResponse`, `EscalationResolveRequest`) and SQLAlchemy table definitions.
   - *Impact:* Eliminated manual typing of standard CRUD validation boilerplate.

3. **Multimodal Vision Prompt Engineering:**
   - Used AI to brainstorm and refine system prompts for Groq Cloud's vision model (`llama-3.2-11b-vision-preview`), ensuring strict JSON formatting with document classification, extracted name, ID number, and legibility status.
   - *Impact:* Accelerated prompt convergence to prevent unstructured model output.

4. **Synthetic Test Payloads & Edge Cases:**
   - Scripted synthetic client payloads in `scratch/` representing real-world dirty inputs: malformed email addresses, 7-digit phone numbers, and cross-entity business documents.

---

## 🧠 3. What I Architected & Decided Myself

1. **Cyclic LangGraph State Machine:**
   - Standard AI assistants default to simple linear chains (`LLMChain` or sequential DAGs). I architected a **cyclic state machine** using LangGraph with interrupt primitives, handling looping document retries, human escalations, and resumes within a unified graph topology.

2. **Session-First Persistence Architecture:**
   - Rather than creating transient random session IDs that require the user to store a long token, I tied the LangGraph checkpointer (`AsyncPostgresSaver`) directly to the customer's verified **email address**.
   - This enabled frictionless cross-session resumption: whenever a customer returns and identifies with their email, their exact state, chat history, and document approvals are instantly re-hydrated.

3. **Write-Consolidation Strategy (Latency Optimization):**
   - Under initial profiling, writing every trivial conversational turn to serverless PostgreSQL (Neon) resulted in 2.0–2.5s turnaround latency per message.
   - I diagnosed the bottleneck and redesigned the persistence layer: intermediate conversational state is maintained in LangGraph working memory, and writes to PostgreSQL are consolidated only at critical business milestones (attempt failure, 3rd-strike escalation, document verification). This reduced message turnaround time to **<850ms (a 60% latency reduction)**.

4. **Mathematical Urgency Formula (SLA Intelligence Engine):**
   - Designed the SLA scoring formula ($\mathcal{U}$) that mathematically weights overdue hours and percentage thresholds:
     $$\text{Breached}: \mathcal{U} = 1000 + (\text{Overdue Hours} \times 10)$$
     $$\text{At-Risk}: \mathcal{U} = 500 + \text{SLA Used \%}$$
     $$\text{On-Track}: \mathcal{U} = 100 + \text{SLA Used \%}$$
   - This ensures operations teams always see the most critical, deadline-threatened customers at the very top of their dashboard.

5. **Tri-State Operational Security Boundary:**
   - Formulated the 3 explicit operator choices (Approve with Override, Request Re-upload, Reject Application).
   - Enforced a strict security boundary: rejected accounts are permanently locked in the database with subsequent requests terminating at `HTTP 403 Forbidden`.

---

## 🚫 4. What AI-Generated Output I Rejected or Corrected

1. **Rejected Infinite Conversational Retry Loops:**
   - *AI Suggestion:* Early AI-generated agent workflows relied on continuous conversational prompting when a document was invalid (e.g., repeatedly asking *"Please upload a better picture"* forever).
   - *My Correction:* In production, this causes massive token waste and user frustration. I rejected this pattern and enforced a **deterministic 3-strike ceiling**: after 3 failed verification attempts, the loop terminates immediately, persists the failing document, and escalates to human review.

2. **Fixed Document Re-Prompt Loop on Human Approval:**
   - *AI Suggestion:* Default graph resumption logic attempted to re-run the previous document prompt upon waking from human review, asking the customer for the same file that had just been approved.
   - *My Correction:* Engineered custom state short-circuiting logic that updates the verified document array, resets the strike counter, and advances the internal document pointer to the *next* required file before resuming the chat stream.

3. **Eliminated Synchronous Blocking Database Calls:**
   - *AI Suggestion:* AI generated standard synchronous SQLAlchemy calls inside asynchronous agent nodes. Under concurrent user load, this blocked the FastAPI event loop and threw pool exhaustion errors.
   - *My Correction:* Refactored all database operations to use asynchronous pooled connections (`AsyncConnectionPool`) with TCP keepalives and automated reconnection (`pool_pre_ping=True`).

4. **Corrected Name Matching Logic on Business Documents:**
   - *AI Suggestion:* AI initially proposed matching the customer's personal name against every uploaded document.
   - *My Correction:* Recognized that business documents (GST certificates, Company Incorporation papers) contain entity names (e.g., "Acme Corp") rather than personal founder names. I decoupled personal document validation (PAN/Aadhaar) from corporate document validation (GST/CIN).

---

## 🏁 5. Conclusion

AI accelerated the routine scaffolding, styling, and schema definitions of FlowAI. However, the system's reliability, latency performance, resilience against serverless database drops, and robust human-in-the-loop escalation were the direct result of deliberate human engineering design.
