/**
 * SupportFlow AI — Auth API Service
 */

import { apiClient } from "./client";
import { LoginPayload, RegisterPayload, TokenResponse, User } from "@/types";

export const authApi = {
  login: async (payload: LoginPayload): Promise<TokenResponse> => {
    const res = await apiClient.post<TokenResponse>("/api/v1/auth/login", payload);
    if (res.access_token) {
      apiClient.setToken(res.access_token);
    }
    return res;
  },

  register: async (payload: RegisterPayload): Promise<User> => {
    return apiClient.post<User>("/api/v1/auth/register", payload);
  },

  getMe: async (): Promise<User> => {
    return apiClient.get<User>("/api/v1/auth/me");
  },

  logout: (): void => {
    apiClient.setToken(null);
  },
};
