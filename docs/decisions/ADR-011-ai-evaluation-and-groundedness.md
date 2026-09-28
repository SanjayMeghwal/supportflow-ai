# ADR-011: AI Evaluation, Grounding, and Faithfulness Verification

**Status:** Accepted  
**Phase:** 13  
**Date:** 2026-09-28  
**Branch:** `feature/evaluation`  
**Author:** SupportFlow AI Engineering Team

---

## 1. Context and Problem Statement

Throughout Phases 6 through 12, SupportFlow AI built a multi-stage retrieval and generation architecture:
1. Vector similarity search via `pgvector`
2. Lexical full-text search via PostgreSQL `tsvector`
3. Hybrid rank fusion via Reciprocal Rank Fusion (RRF)
4. Cross-encoder re-ranking via `ms-marco-MiniLM-L-6-v2`
5. LangGraph RAG orchestration with bounded AI tool execution
6. Human-in-the-loop review and deterministic escalation guardrails

While conventional unit and integration tests verified API contracts, database integrity, and state transitions, they could not answer foundational AI quality and alignment questions:
- *Did the retrieval layer locate the true source documents, or did it return irrelevant distractors?*
- *Was the retrieved context actually used, or was it noise?*
- *Did the generated answer address the customer's actual question intent?*
- *Was the answer fully grounded in the retrieved context, or did it hallucinate unverified facts?*
- *Can we evaluate retrieval quality across stages without relying on live external LLM API calls?*

Without empirical evaluation metrics and a versioned benchmark dataset, engineering teams cannot detect regressions when updating embedding models, chunking strategies, prompt templates, or re-ranking weights.

---

## 2. Architectural Principle: Separation of Evaluation from Runtime

Evaluation is maintained as an **independent layer** (`backend/app/evaluation/` and `scripts/run_evaluation.py`) rather than embedding evaluation overhead into customer-facing production request paths.

```
                    +-----------------------+
                    | Benchmark Dataset     |
                    | (20 curated samples)  |
                    +-----------+-----------+
                                |
                                v
                    +-----------------------+
                    | Evaluation Runner     |
                    +-----------+-----------+
                                |
         +----------------------+----------------------+
         |                                             |
         v                                             v
+------------------------+                 +------------------------+
|  Retrieval Evaluation  |                 | RAG Quality Evaluation |
|  - Precision@K         |                 | - Context Relevance    |
|  - Recall@K            |                 | - Answer Relevance     |
|  - MRR                 |                 | - Faithfulness / Claims|
|  - Hit Rate@K          |                 | - Hallucination Rate   |
+------------------------+                 +------------------------+
         |                                             |
         +----------------------+----------------------+
                                |
                                v
                    +-----------------------+
                    | Evaluation Report     |
                    | (Console, MD, JSON)   |
                    +-----------------------+
```

---

## 3. Decisions & Metrics Implemented

### 3.1 Benchmark Dataset Design
- Created a deterministic, portable benchmark dataset with 20 realistic customer support questions across key operational categories: `authentication`, `refund`, `orders`, `shipping`, `payments`, `cancellation`, and `general_policy`.
- Explicitly incorporated **negative / out-of-domain samples** (`out_of_domain`, `security_refusal`) where knowledge is intentionally absent. This tests whether the RAG pipeline correctly issues refusals rather than hallucinating answers.
- Eliminated dependencies on environment-specific database auto-increment IDs or developer UUIDs.

### 3.2 Retrieval Metrics
1. **Precision@K**:
   $$\text{Precision@K} = \frac{|\text{Retrieved Top-K} \cap \text{Relevant Items}|}{K}$$
   Measures the density of relevant context in the top-$K$ candidates passed to the LLM context window.
2. **Recall@K**:
   $$\text{Recall@K} = \frac{|\text{Retrieved Top-K} \cap \text{Relevant Items}|}{|\text{Relevant Items}|}$$
   Measures whether the retrieval pipeline captured all necessary ground-truth facts.
3. **Mean Reciprocal Rank (MRR)**:
   $$\text{MRR} = \frac{1}{\text{rank of first relevant item}}$$
   Measures ranking efficacy, ensuring true answers appear at the highest positions.
4. **Hit Rate@K**: Binary indicator of whether at least one relevant passage reached the top-$K$.

### 3.3 Context Relevance
- Measures what proportion of retrieved passages contain informative content relevant to the customer query and ground-truth reference context.
- Handles empty/negative queries gracefully: correctly assigns 1.0 when an unanswerable query has zero retrieved context, and penalizes irrelevant chunks retrieved for negative prompts.

### 3.4 Answer Relevance
- Evaluates whether the generated response directly addresses the inquiry and matches reference ground truth:
  - Query intent keyword coverage
  - Token F1 overlap against authoritative reference answers
  - Exact handling of refusals: an explicit refusal on an unanswerable query is scored as 1.0, whereas an ungrounded refusal on an answerable query is heavily penalized.

### 3.5 Faithfulness and Groundedness (RAGAS-Style)
- **Claim Extraction**: Decomposes the synthesized response into discrete factual assertions, filtering out conversational pleasantries ("Thank you for reaching out") and markdown bullet artifacts without altering factual quantities (e.g., "30 days").
- **Claim Verification**: Each extracted claim is verified against the retrieved context:
  - Exact substring presence
  - Entity and numerical fact containment (flags numerical hallucinations, e.g. "90 days" when context specifies "30 days")
  - Informative token overlap thresholding ($\ge 65\%$ overlap ratio)
- **Faithfulness Score**:
  $$\text{Faithfulness} = \frac{\text{Supported Claims}}{\text{Total Factual Claims}}$$
- **Hallucination Detection**: Flagged if any factual claim lacks context grounding.

### 3.6 Pluggable LLM Judge Support
- Deterministic NLP claim evaluation is used by default for zero-cost, offline, reproducible testing.
- An optional LLM judge mode is supported via `FaithfulnessEvaluator(llm_service=...)` leveraging the existing `BaseLLMService` abstraction. If an external model is configured, it prompts the judge with structured JSON output instructions, and falls back to deterministic verification if output parsing fails.

---

## 4. Why RAGAS Was Not Blindly Installed

Rather than pulling the third-party `ragas` library into `requirements.txt`:
1. **Dependency Bloat & Version Conflicts**: `ragas` introduces dozens of heavy transitive dependencies (OpenAI client, datasets, langchain-community, huggingface-hub) which can clash with `langgraph` and pin conflicting Pydantic versions.
2. **External API Key Hard Dependencies**: Default RAGAS runs require active OpenAI/Anthropic API credentials, conflicting with our rule that test suites must run completely offline without cost or network access.
3. **Explainability & Interview Readiness**: Implementing the core RAGAS mathematical concepts (Precision@K, Recall@K, MRR, Context Relevance, Claim Extraction, and Faithfulness) directly in `backend/app/evaluation/` provides complete algorithmic transparency and zero vendor lock-in.

---

## 5. Distinction Between System Layers

It is essential to distinguish the three operational checks:
1. **Retrieval Evaluation**: Measures retrieval candidate quality against labeled benchmark document/chunk identifiers.
2. **RAG Quality Evaluation**: Measures post-generation faithfulness, context relevance, and refusal behavior.
3. **Human-in-the-Loop Review**: An operational safety workflow that routes edge cases, low-confidence responses, and keyword-triggered tickets to human agents before sending them to customers.

Automated metrics are **indicators**, not proofs of absolute correctness. They enable regression tracking and quantitative optimization.

---

## 6. Security and Offline Execution

- **Zero Secret Exposure**: Benchmark datasets and evaluation scripts do not require, log, or commit API keys or database passwords.
- **Isolated Offline Mode**: All 56 Phase 13 unit tests execute in under 1 second without network access.
- **Safe CLI Runner**: `scripts/run_evaluation.py` writes structured JSON reports to `evaluation/results/latest_report.json` with execution timestamps and category summaries.
