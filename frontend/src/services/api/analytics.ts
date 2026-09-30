/**
 * SupportFlow AI — Operations & Observability Analytics API Service (Phases 14 & 17)
 */

import { apiClient } from "./client";
import {
  AnalyticsSummary,
  LLMAnalyticsSummary,
  ObservabilityOverview,
  RequestMetrics,
} from "@/types";

export const analyticsApi = {
  getSummary: async (): Promise<AnalyticsSummary> => {
    return apiClient.get<AnalyticsSummary>("/api/v1/analytics/summary");
  },

  getObservabilityOverview: async (): Promise<ObservabilityOverview> => {
    return apiClient.get<ObservabilityOverview>(
      "/api/v1/analytics/observability/overview"
    );
  },

  getRequestMetrics: async (): Promise<RequestMetrics> => {
    return apiClient.get<RequestMetrics>(
      "/api/v1/analytics/observability/requests"
    );
  },

  getLLMAnalytics: async (
    period: string = "24h"
  ): Promise<LLMAnalyticsSummary> => {
    return apiClient.get<LLMAnalyticsSummary>(
      `/api/v1/analytics/observability/llm?period=${period}`
    );
  },
};
