import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { ApiClient } from "@/services/api/client";
import { APIError } from "@/types";

describe("ApiClient", () => {
  let client: ApiClient;

  beforeEach(() => {
    localStorage.clear();
    client = new ApiClient();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sets, gets, and persists auth tokens", () => {
    client.setToken("test-jwt-token");
    expect(client.getToken()).toBe("test-jwt-token");
    expect(localStorage.getItem("supportflow_access_token")).toBe("test-jwt-token");

    client.setToken(null);
    expect(client.getToken()).toBeNull();
    expect(localStorage.getItem("supportflow_access_token")).toBeNull();
  });

  it("automatically attaches Authorization Bearer header when token is set", async () => {
    client.setToken("secret-token");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ success: true }),
    } as unknown as Response);

    await client.get("/api/v1/auth/me");

    expect(fetchSpy).toHaveBeenCalled();
    const calls = fetchSpy.mock.calls[0];
    const headers = calls[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer secret-token");
  });

  it("handles 401 unauthorized and invokes callback", async () => {
    const unauthorizedSpy = vi.fn();
    client.onUnauthorized(unauthorizedSpy);
    client.setToken("expired-token");

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      status: 401,
      ok: false,
      json: async () => ({ detail: "Token expired" }),
    } as unknown as Response);

    await expect(client.get("/api/v1/auth/me")).rejects.toThrow(APIError);
    expect(client.getToken()).toBeNull();
    expect(unauthorizedSpy).toHaveBeenCalled();
  });

  it("correctly extracts FastAPI validation errors in detail array", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      status: 422,
      ok: false,
      json: async () => ({
        detail: [
          { msg: "Field 'title' is required", loc: ["body", "title"] },
          { msg: "Field 'description' is too short", loc: ["body", "description"] },
        ],
      }),
    } as unknown as Response);

    try {
      await client.post("/api/v1/tickets", {});
      expect.unreachable("Should have thrown APIError");
    } catch (err) {
      expect(err).toBeInstanceOf(APIError);
      expect((err as APIError).message).toContain("Field 'title' is required");
      expect((err as APIError).message).toContain("Field 'description' is too short");
    }
  });

  it("handles network failure gracefully", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Network connection failed"));

    try {
      await client.get("/api/v1/tickets");
      expect.unreachable("Should have thrown APIError");
    } catch (err) {
      expect(err).toBeInstanceOf(APIError);
      expect((err as APIError).status).toBe(0);
      expect((err as APIError).message).toContain("Unable to connect to SupportFlow server");
    }
  });
});
