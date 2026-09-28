/**
 * SupportFlow AI — Human Review API Service (Phase 12 / Phase 14)
 *
 * Backend endpoints (all require SUPPORT_AGENT or ADMIN role):
 *   GET  /api/v1/reviews/pending       — paginated pending reviews
 *   GET  /api/v1/reviews/{id}          — review detail with tool invocations
 *   POST /api/v1/reviews/{id}/approve  — approve AI draft
 *   POST /api/v1/reviews/{id}/edit     — edit AI draft before sending
 *   POST /api/v1/reviews/{id}/reject   — reject and route to manual handling
 *   POST /api/v1/reviews/{id}/escalate — escalate to higher-tier agent
 */

import { apiClient } from "./client";
import {
  ReviewApprovePayload,
  ReviewDetail,
  ReviewEditPayload,
  ReviewEscalatePayload,
  ReviewItem,
  ReviewListResponse,
  ReviewRejectPayload,
} from "@/types";

interface ListReviewsParams {
  skip?: number;
  limit?: number;
  /** Reserved for future backend filtering; currently ignored by server */
  status?: string;
}

export const reviewsApi = {
  /**
   * List reviews from the pending queue.
   * Note: The backend /pending endpoint only returns PENDING reviews.
   * The `status` filter param is accepted for forward-compatibility but
   * currently the backend does not support filtering by non-PENDING status
   * on this endpoint.
   */
  listReviews: async (params?: ListReviewsParams): Promise<ReviewListResponse> => {
    const query = new URLSearchParams();
    if (params?.skip !== undefined) query.set("skip", params.skip.toString());
    if (params?.limit !== undefined) query.set("limit", params.limit.toString());
    const qs = query.toString();
    const endpoint = qs ? `/api/v1/reviews/pending?${qs}` : "/api/v1/reviews/pending";
    return apiClient.get<ReviewListResponse>(endpoint);
  },

  /** @deprecated Use listReviews instead */
  getPendingReviews: async (params?: { skip?: number; limit?: number }): Promise<ReviewListResponse> => {
    const query = new URLSearchParams();
    if (params?.skip !== undefined) query.set("skip", params.skip.toString());
    if (params?.limit !== undefined) query.set("limit", params.limit.toString());
    const qs = query.toString();
    const endpoint = qs ? `/api/v1/reviews/pending?${qs}` : "/api/v1/reviews/pending";
    return apiClient.get<ReviewListResponse>(endpoint);
  },

  getReviewDetail: async (reviewId: string): Promise<ReviewDetail> => {
    return apiClient.get<ReviewDetail>(`/api/v1/reviews/${reviewId}`);
  },

  approveReview: async (reviewId: string, payload: ReviewApprovePayload = {}): Promise<ReviewItem> => {
    return apiClient.post<ReviewItem>(`/api/v1/reviews/${reviewId}/approve`, payload);
  },

  editReview: async (reviewId: string, payload: ReviewEditPayload): Promise<ReviewItem> => {
    return apiClient.post<ReviewItem>(`/api/v1/reviews/${reviewId}/edit`, payload);
  },

  rejectReview: async (reviewId: string, payload: ReviewRejectPayload): Promise<ReviewItem> => {
    return apiClient.post<ReviewItem>(`/api/v1/reviews/${reviewId}/reject`, payload);
  },

  escalateReview: async (reviewId: string, payload: ReviewEscalatePayload): Promise<ReviewItem> => {
    return apiClient.post<ReviewItem>(`/api/v1/reviews/${reviewId}/escalate`, payload);
  },
};
