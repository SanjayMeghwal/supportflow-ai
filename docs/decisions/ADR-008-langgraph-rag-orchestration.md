# ADR-008: LangGraph Core Orchestration for Grounded RAG Response Synthesis

## Status
Accepted

## Context
In Phases 7–9 (ADRs 005, 006, 007), SupportFlow AI developed an enterprise multi-stage knowledge retrieval architecture:
1. **Dense Vector Retrieval:** `bge-small-en-v1.5` embeddings over PostgreSQL `pgvector` HNSW indexes.
2. **PostgreSQL Full-Text Search:** Lexical queries over GIN `tsvector` indexes.
3. **Reciprocal Rank Fusion (RRF):** Bounded candidate fusion ($k=60$) balancing semantic concepts and exact keyword matches.
4. **Cross-Encoder Reranking:** Local `ms-marco-MiniLM-L-6-v2` cross-attention model for fine-grained contextual precision.

However, isolated retrieval results alone do not provide a reliable conversational support platform. The system requires an explicit orchestration layer to:
- Coordinate retrieval, context assembly, LLM generation, and validation as discrete deterministic state transitions.
- Conditionally branch based on knowledge availability (short-circuiting LLM inference when context is missing to prevent hallucinations and eliminate unnecessary token costs).
- Enforce strict factual grounding in the LLM synthesis prompt.
- Propagate source citations and passage provenance back to the caller.
- Maintain rigorous separation from future phases (Phase 11 tools, Phase 12 human review, Phase 13 evaluation).

## Decision
We implement **Phase 10: LangGraph Core Orchestration** using LangGraph's state graph architecture (`StateGraph`) with an explicit `AgentState` schema and a decoupled LLM abstraction.

### 1. State Graph Architecture

```text
                        START
                          │
                          ▼
                    [ retrieve ]
              (search_reranked: Vector +
               FTS + RRF + Cross-Encoder)
                          │
                          ▼
                [ context_assembly ]
             (Build structured context
              and extract source metadata)
                          │
                          ▼
                 context_available?
                /                  \
          [ YES ]                  [ NO ]
            │                        │
            ▼                        ▼
    [ generate_answer ]     [ insufficient_context ]
   (Groq LLM with strict    (Safe fallback notice;
    grounded system prompt)  no LLM token spend)
            │                        │
            ▼                        │
    [ validate_format ]              │
   (Deterministic whitespace         │
    and completeness check)          │
            │                        │
            ▼                        ▼
           END                      END
```

### 2. State Schema (`AgentState`)
The workflow operates on a typed state dictionary:
- `query` (*str*): The inbound customer inquiry.
- `top_k` (*int*): Candidate passage count for retrieval.
- `retrieved_docs` (*list[dict]*): Candidate chunks returned by multi-stage retrieval.
- `context_text` (*str*): Formatted reference text blocks provided to the LLM.
- `sources` (*list[dict]*): Cleaned citation metadata (`chunk_id`, `document_id`, `document_title`, `chunk_index`, `content`, `score`).
- `context_available` (*bool*): True if relevant passages were retrieved.
- `answer` (*str*): Final synthesized answer or fallback notice.
- `is_valid` (*bool*): Output validation flag.
- `error` (*Optional[str]*): Any pipeline warning or validation message.

### 3. Decoupled LLM Client Abstraction
An abstract interface `BaseLLMService` decouples the core graph logic from concrete LLM providers:
- **`GroqLLMService`:** High-throughput, low-latency inference using Groq's API (`llama-3.3-70b-versatile`) with temperature set to `0.0` for deterministic outputs.
- **`MockLLMService`:** In-memory mock implementing the same protocol for offline testing and continuous integration without requiring paid credentials or network access.

### 4. Deterministic Gating & Insufficient Context Handling
Rather than permitting the LLM to speculate when reference material is lacking, the conditional router inspects `context_available`:
- If `context_available == False`, the pipeline branches directly to the `insufficient_context` node, generating a deterministic fallback notice (*"I do not have sufficient information in the knowledge base to answer your question..."*).
- The LLM is **never** invoked for ungrounded queries, eliminating hallucination risks and saving LLM inference latency and token quota.

### 5. Architectural Phase Boundaries
To maintain codebase hygiene, Phase 10 strictly adheres to the following boundaries:
- **In-Scope (Phase 10):** LangGraph state graph, retrieval node, context assembly, answer synthesis via Groq, deterministic format validation, conditional context routing, source citation propagation, `POST /knowledge/ask` endpoint, automated tests.
- **Excluded (Phase 11):** Autonomous internal tools (order lookup, payment status verification, sandboxed actions).
- **Excluded (Phase 12):** Human-In-The-Loop (HITL) review queues, approval state machines, agent escalation workflows.
- **Excluded (Phase 13):** Evaluation frameworks (Ragas), automated faithfulness/relevance benchmarks, evaluation datasets.

## Consequences

### Positive
- **Predictable Control Flow:** Graph execution order, conditional routing, and state transitions are explicitly declared and easily testable.
- **Zero Hallucination on Missing Context:** Deterministic short-circuiting ensures zero LLM hallucinations when no matching knowledge base entries exist.
- **Auditable Provenance:** Every response carries structured source citations linking directly to underlying `DocumentChunk` and `KnowledgeDocument` IDs.
- **Isolated Testing:** Test suites execute 100% offline using `MockLLMService`, preventing flaky tests or API key requirements in CI.

### Trade-offs & Limitations
- **Single-Turn Workflow:** Phase 10 focuses on single-turn inquiry resolution. Multi-turn conversation state persistence and agent checkpointing will build on this foundation in later phases.
- **Dependency on Retrieval Precision:** The quality of the synthesized answer is fundamentally bounded by the recall and precision of the Phase 7–9 retrieval stack.
