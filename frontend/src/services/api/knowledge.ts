/**
 * SupportFlow AI — Knowledge Base & RAG API Service
 *
 * Backend endpoints:
 *   GET  /api/v1/knowledge             — list knowledge documents (paginated)
 *   GET  /api/v1/knowledge/{id}        — document detail with chunks
 *   POST /api/v1/knowledge/search      — hybrid/vector/FTS search
 *   POST /api/v1/knowledge/ask         — RAG query endpoint
 */

import { apiClient } from "./client";
import {
  KnowledgeDocumentDetail,
  KnowledgeDocumentListResponse,
  KnowledgeSearchResponse,
  RAGQueryResponse,
} from "@/types";

export const knowledgeApi = {
  /** List all ingested knowledge documents with pagination. */
  listDocuments: async (params?: { offset?: number; limit?: number }): Promise<KnowledgeDocumentListResponse> => {
    const query = new URLSearchParams();
    if (params?.offset !== undefined) query.set("offset", params.offset.toString());
    if (params?.limit !== undefined) query.set("limit", params.limit.toString());
    const qs = query.toString();
    const endpoint = qs ? `/api/v1/knowledge?${qs}` : "/api/v1/knowledge";
    return apiClient.get<KnowledgeDocumentListResponse>(endpoint);
  },

  /** Get a single document with all its chunks. */
  getDocumentDetail: async (documentId: string): Promise<KnowledgeDocumentDetail> => {
    return apiClient.get<KnowledgeDocumentDetail>(`/api/v1/knowledge/${documentId}`);
  },

  /**
   * Multi-stage hybrid semantic search.
   * @param query     Natural language or keyword query
   * @param searchType  Retrieval strategy: vector | full_text | hybrid | reranked
   * @param topK      Number of results to return
   */
  search: async (
    query: string,
    searchType: "vector" | "full_text" | "hybrid" | "reranked" = "hybrid",
    topK = 5
  ): Promise<KnowledgeSearchResponse> => {
    return apiClient.post<KnowledgeSearchResponse>("/api/v1/knowledge/search", {
      query,
      search_type: searchType,
      top_k: topK,
    });
  },

  /**
   * RAG query: retrieves context and synthesizes a grounded answer.
   * @param query   Customer/agent question
   * @param topK    Context chunks to retrieve
   */
  ask: async (query: string, topK = 5): Promise<RAGQueryResponse> => {
    return apiClient.post<RAGQueryResponse>("/api/v1/knowledge/ask", {
      query,
      top_k: topK,
    });
  },
};
