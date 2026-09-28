/**
 * SupportFlow AI — Centralized HTTP Client
 * Enforces strict typing, header injection, bearer token handling, and robust error extraction.
 */

import { APIError, APIErrorResponse } from "@/types";

const TOKEN_STORAGE_KEY = "supportflow_access_token";

export class ApiClient {
  private baseUrl: string;
  private token: string | null = null;
  private onUnauthorizedCallback?: () => void;

  constructor() {
    this.baseUrl = import.meta.env.VITE_API_BASE_URL || "";
    // Initialize token from storage if present in browser
    if (typeof window !== "undefined") {
      this.token = localStorage.getItem(TOKEN_STORAGE_KEY);
    }
  }

  public setToken(token: string | null): void {
    this.token = token;
    if (typeof window !== "undefined") {
      if (token) {
        localStorage.setItem(TOKEN_STORAGE_KEY, token);
      } else {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
      }
    }
  }

  public getToken(): string | null {
    return this.token;
  }

  public onUnauthorized(callback: () => void): void {
    this.onUnauthorizedCallback = callback;
  }

  public async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = endpoint.startsWith("http")
      ? endpoint
      : `${this.baseUrl}${endpoint}`;

    const headers = new Headers(options.headers || {});

    // Attach Bearer Token if present
    if (this.token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${this.token}`);
    }

    // Set JSON content-type if body is provided and not FormData
    if (
      options.body &&
      !(options.body instanceof FormData) &&
      !headers.has("Content-Type")
    ) {
      headers.set("Content-Type", "application/json");
    }

    let response: Response;
    try {
      response = await fetch(url, {
        ...options,
        headers,
      });
    } catch (networkError) {
      throw new APIError(
        "Unable to connect to SupportFlow server. Please check your internet connection.",
        0,
        networkError
      );
    }

    // Handle 204 No Content
    if (response.status === 204) {
      return {} as T;
    }

    // Handle 401 Unauthorized
    if (response.status === 401) {
      this.setToken(null);
      if (this.onUnauthorizedCallback) {
        this.onUnauthorizedCallback();
      }
      throw new APIError("Authentication required or session expired. Please sign in.", 401);
    }

    // Try parsing JSON response
    let data: unknown;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      const errResponse = data as APIErrorResponse | null;
      let message = "An unexpected error occurred.";

      if (errResponse?.detail) {
        if (typeof errResponse.detail === "string") {
          message = errResponse.detail;
        } else if (Array.isArray(errResponse.detail)) {
          message = errResponse.detail.map((d) => d.msg).join(", ");
        }
      } else if (response.status === 403) {
        message = "You do not have permission to perform this action.";
      } else if (response.status === 404) {
        message = "The requested resource could not be found.";
      } else if (response.status === 409) {
        message = "A conflict occurred while processing your request.";
      } else if (response.status >= 500) {
        message = "Server error. Our engineering team has been notified.";
      }

      throw new APIError(message, response.status, data);
    }

    return data as T;
  }

  public get<T>(endpoint: string, options?: RequestInit): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: "GET" });
  }

  public post<T>(
    endpoint: string,
    body?: unknown,
    options?: RequestInit
  ): Promise<T> {
    const isFormData = body instanceof FormData;
    return this.request<T>(endpoint, {
      ...options,
      method: "POST",
      body: isFormData ? body : JSON.stringify(body),
    });
  }

  public patch<T>(
    endpoint: string,
    body?: unknown,
    options?: RequestInit
  ): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: "PATCH",
      body: JSON.stringify(body),
    });
  }

  public delete<T>(endpoint: string, options?: RequestInit): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: "DELETE" });
  }
}

export const apiClient = new ApiClient();
