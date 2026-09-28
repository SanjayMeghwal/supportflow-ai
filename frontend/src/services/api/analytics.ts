/**
 * SupportFlow AI — Operations Analytics API Service (Phase 14)
 */

import { apiClient } from "./client";
import { AnalyticsSummary } from "@/types";

export const analyticsApi = {
  getSummary: async (): Promise<AnalyticsSummary> => {
    return apiClient.get<AnalyticsSummary>("/api/v1/analytics/summary");
  },
};
