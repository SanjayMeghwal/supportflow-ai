/**
 * SupportFlow AI — TypeScript Core Domain Types
 * Matches FastAPI backend models and Pydantic schemas exactly.
 */

// ---------------------------------------------------------------------------
// Authentication & Users
// ---------------------------------------------------------------------------

export type UserRole = "CUSTOMER" | "SUPPORT_AGENT" | "ADMIN";

export interface User {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  full_name?: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface RegisterPayload {
  email: string;
  password: string;
  full_name: string;
}

// ---------------------------------------------------------------------------
// Ticket Management
// ---------------------------------------------------------------------------

export type TicketStatus =
  | "OPEN"
  | "AI_PROCESSING"
  | "PENDING_CUSTOMER"
  | "PENDING_AGENT_REVIEW"
  | "IN_PROGRESS"
  | "RESOLVED"
  | "CLOSED";

export type TicketPriority = "LOW" | "MEDIUM" | "HIGH" | "URGENT";

export type TicketCategory =
  | "BILLING"
  | "ORDER_STATUS"
  | "TECHNICAL"
  | "RETURNS"
  | "GENERAL";

export type SenderType = "CUSTOMER" | "AGENT" | "AI_SYSTEM";

export interface TicketMessage {
  id: string;
  ticket_id: string;
  sender_id?: string | null;
  sender_type: SenderType;
  content: string;
  is_internal_note: boolean;
  created_at: string;
}

export interface Ticket {
  id: string;
  ticket_number: string;
  customer_id: string;
  assigned_agent_id?: string | null;
  title: string;
  description: string;
  category: TicketCategory;
  priority: TicketPriority;
  status: TicketStatus;
  resolution_summary?: string | null;
  closed_at?: string | null;
  created_at: string;
  updated_at: string;
  messages?: TicketMessage[];
}

export interface TicketCreatePayload {
  title: string;
  description: string;
  category: TicketCategory;
}
export type CreateTicketRequest = TicketCreatePayload;

export interface TicketUpdatePayload {
  status?: TicketStatus;
  priority?: TicketPriority;
  category?: TicketCategory;
  resolution_summary?: string;
}
export type UpdateTicketRequest = TicketUpdatePayload;

export interface TicketMessageCreatePayload {
  content: string;
  is_internal_note?: boolean;
}

export interface TicketListResponse {
  tickets: Ticket[];
  total: number;
  offset: number;
  limit: number;
}

export interface TicketFilterParams {
  offset?: number;
  limit?: number;
  status?: TicketStatus;
  category?: TicketCategory;
  priority?: TicketPriority;
}

// ---------------------------------------------------------------------------
// Human-In-The-Loop Reviews (Phase 12)
// ---------------------------------------------------------------------------

export type ReviewStatus =
  | "PENDING"
  | "APPROVED"
  | "EDITED"
  | "REJECTED"
  | "ESCALATED";

export type ReviewAction = "APPROVED" | "EDITED" | "REJECTED" | "ESCALATED";

export interface ToolInvocation {
  id: string;
  tool_name: string;
  input_parameters: Record<string, unknown>;
  output_result: Record<string, unknown>;
  is_success: boolean;
  duration_ms?: number | null;
}

export interface ReviewItem {
  id: string;
  ticket_id: string;
  ai_run_id: string;
  status: ReviewStatus;
  escalation_reason: string;
  original_ai_draft: string;
  final_submitted_text?: string | null;
  feedback_notes?: string | null;
  reviewer_id?: string | null;
  action_taken?: ReviewAction | null;
  created_at: string;
  updated_at: string;
  resolved_at?: string | null;
  ticket_number?: string | null;
  ticket_title?: string | null;
  ticket_priority?: string | null;
  ticket_category?: string | null;
}

export interface ReviewDetail extends ReviewItem {
  confidence_score?: number | null;
  intent_detected?: string | null;
  model_name?: string | null;
  tool_invocations: ToolInvocation[];
}

export interface ReviewListResponse {
  total: number;
  items: ReviewItem[];
}

export interface ReviewApprovePayload {
  notes?: string;
  resolve_ticket?: boolean;
}

export interface ReviewEditPayload {
  final_submitted_text: string;
  notes?: string;
  resolve_ticket?: boolean;
}

export interface ReviewRejectPayload {
  feedback_notes: string;
}

export interface ReviewEscalatePayload {
  feedback_notes: string;
  assign_to_agent_id?: string;
}

// ---------------------------------------------------------------------------
// Operations Analytics (Phase 14)
// ---------------------------------------------------------------------------

/**
 * Mirrors backend AnalyticsSummaryResponse exactly.
 * NOTE: This endpoint does NOT return ai_resolution_rate, avg_confidence_score,
 * avg_resolution_time_minutes, critical_tickets, status_breakdown, or
 * priority_breakdown — those do not exist in the backend schema.
 */
export interface AnalyticsSummary {
  total_tickets: number;
  open_tickets: number;
  resolved_tickets: number;
  in_progress_tickets: number;
  pending_review_tickets: number;
  closed_tickets: number;
  total_reviews: number;
  pending_reviews: number;
  completed_reviews: number;
  total_ai_runs: number;
  average_confidence?: number | null;
  tickets_by_status: Record<string, number>;
  tickets_by_category: Record<string, number>;
  tickets_by_priority: Record<string, number>;
  reviews_by_status: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Knowledge Base
// ---------------------------------------------------------------------------

export interface KnowledgeDocument {
  id: string;
  title: string;
  source_type: string;
  source_uri?: string | null;
  checksum_sha256: string;
  is_active: boolean;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentChunk {
  id: string;
  document_id: string;
  chunk_index: number;
  chunk_text: string;
  metadata_json?: Record<string, unknown>;
  created_at: string;
}

export interface KnowledgeDocumentDetail extends KnowledgeDocument {
  chunks: DocumentChunk[];
}

export interface KnowledgeDocumentListResponse {
  documents: KnowledgeDocument[];
  total: number;
  offset: number;
  limit: number;
}

export interface KnowledgeSearchResultItem {
  chunk_id: string;
  document_id: string;
  document_title: string;
  chunk_index: number;
  content: string;
  score: number;
  vector_rank?: number | null;
  fts_rank?: number | null;
  rrf_score?: number | null;
  rerank_score?: number | null;
  metadata?: Record<string, unknown>;
}

export interface KnowledgeSearchResponse {
  query: string;
  search_type: string;
  total_results: number;
  results: KnowledgeSearchResultItem[];
}

export interface RAGSourceItem {
  chunk_id: string;
  document_id: string;
  document_title: string;
  chunk_index: number;
  content: string;
  score: number;
  metadata?: Record<string, unknown>;
}

export interface RAGQueryResponse {
  query: string;
  answer: string;
  context_found: boolean;
  sources: RAGSourceItem[];
}

// ---------------------------------------------------------------------------
// API Client & Errors
// ---------------------------------------------------------------------------

export interface APIErrorResponse {
  detail?: string | Array<{ msg: string; loc: string[] }>;
}

export class APIError extends Error {
  status: number;
  details?: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "APIError";
    this.status = status;
    this.details = details;
  }
}
