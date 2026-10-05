# Data Models — Reference

> Companion document to [architecture.md](../architecture.md)  
> Source: `backend/app/models/`

---

## Base Mixins

All domain models inherit from two mixins defined in `models/base.py`:

| Mixin | Columns added |
|---|---|
| `UUIDPrimaryKeyMixin` | `id: UUID` (v4, default_factory=uuid4, primary key) |
| `TimestampMixin` | `created_at: datetime` (UTC, server default), `updated_at: datetime` (UTC, auto-updated) |

---

## Entity Relationship Overview

```
User (1) ──────── (1) Customer
 │
 └──(via assigned_agent_id) Ticket (N)

Customer (1) ──── (N) Ticket
                       │
                       └── (N) TicketMessage
                       └── (1) AIRun
                                 │
                                 ├── (N) AIToolInvocation
                                 └── (1) HumanReview

Customer (1) ──── (N) Order
                       │
                       └── (N) Payment

KnowledgeDocument (1) ── (N) DocumentChunk
                                 │
                                 └── embedding: vector(384)
                                 └── tsvector_content

AuditLog ─── (polymorphic) any actor + any resource
LLMAnalyticsRecord ─── per LLM API call
```

---

## Model Definitions

### `User` (`users`)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `email` | String | unique, indexed |
| `hashed_password` | String | bcrypt hash |
| `role` | Enum(UserRole) | ADMIN / SUPPORT_AGENT / CUSTOMER |
| `is_active` | Boolean | default True |
| `created_at` | DateTime | UTC |
| `updated_at` | DateTime | UTC |

### `Customer` (`customers`)

| Column | Type | Notes |
|---|---|---|
| `user_id` | UUID | FK → users.id |
| `company_name` | String | optional |
| `tier` | Enum(CustomerTier) | STANDARD / PREMIUM / ENTERPRISE |

### `Ticket` (`tickets`)

| Column | Type | Notes |
|---|---|---|
| `customer_id` | UUID | FK → customers.id |
| `subject` | String | |
| `status` | Enum(TicketStatus) | OPEN / IN_PROGRESS / RESOLVED / CLOSED |
| `priority` | Enum(TicketPriority) | LOW / MEDIUM / HIGH / URGENT |
| `category` | Enum(TicketCategory) | |
| `assigned_agent_id` | UUID | FK → users.id, nullable |

### `TicketMessage` (`ticket_messages`)

| Column | Type | Notes |
|---|---|---|
| `ticket_id` | UUID | FK → tickets.id |
| `content` | Text | |
| `sender_type` | Enum(SenderType) | CUSTOMER / AGENT / AI |

### `Order` (`orders`) + `Payment` (`payments`)

Used by bounded AI tools (`get_order_status`, `get_payment_status`). Tools enforce that requesting customer can only access their own orders.

### `KnowledgeDocument` (`knowledge_documents`)

| Column | Type | Notes |
|---|---|---|
| `title` | String | |
| `source_type` | Enum(SourceType) | PDF / MARKDOWN / TEXT / JSON |
| `sha256_checksum` | String | deduplication key |
| `chunk_count` | Integer | |
| `source_uri` | String | optional |

### `DocumentChunk` (`document_chunks`)

| Column | Type | Notes |
|---|---|---|
| `document_id` | UUID | FK → knowledge_documents.id |
| `chunk_index` | Integer | position within document |
| `content` | Text | raw chunk text |
| `embedding` | Vector(384) | pgvector column; BAAI/bge-small-en-v1.5 |
| `tsvector_content` | TSVector | PostgreSQL full-text search index |
| `metadata` | JSONB | optional document metadata |

### `AIRun` (`ai_runs`)

| Column | Type | Notes |
|---|---|---|
| `ticket_id` | UUID | FK → tickets.id, nullable |
| `query` | Text | sanitized user query |
| `answer` | Text | final answer |
| `status` | Enum(AIRunStatus) | SUCCESS / FAILED / ESCALATED_GUARDRAIL / ESCALATED_LOW_CONFIDENCE |
| `escalation_triggered` | Boolean | |
| `sources_json` | JSONB | citation metadata |
| `latency_ms` | Float | |

### `HumanReview` (`human_reviews`)

| Column | Type | Notes |
|---|---|---|
| `run_id` | UUID | FK → ai_runs.id |
| `status` | Enum(ReviewStatus) | PENDING / APPROVED / REJECTED |
| `escalation_reason` | Text | |
| `reviewer_id` | UUID | FK → users.id, nullable |
| `reviewed_at` | DateTime | nullable |

### `AuditLog` (`audit_logs`)

| Column | Type | Notes |
|---|---|---|
| `actor_id` | UUID | FK → users.id, nullable |
| `action` | String | e.g. `review.approve` |
| `resource_type` | String | e.g. `HumanReview` |
| `resource_id` | UUID | |
| `details` | JSONB | free-form metadata |

### `LLMAnalyticsRecord` (`llm_analytics`)

| Column | Type | Notes |
|---|---|---|
| `operation` | String | e.g. `rag_synthesis`, `tool_synthesis` |
| `model` | String | Groq model name |
| `prompt_tokens` | Integer | |
| `completion_tokens` | Integer | |
| `total_tokens` | Integer | |
| `latency_ms` | Float | |
