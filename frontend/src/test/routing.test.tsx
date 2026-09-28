import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ToastProvider } from "@/components/ui/Toast";
import { ProtectedRoute } from "@/components/layout/ProtectedRoute";
import { LoginPage } from "@/pages/LoginPage";
import * as AuthContextModule from "@/context/AuthContext";
import { User } from "@/types";

const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

describe("Routing & ProtectedRoute", () => {
  it("redirects unauthenticated user to /login", () => {
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      user: null,
      token: null,
      isLoading: false,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
      refreshUser: vi.fn(),
    });

    render(
      <MemoryRouter initialEntries={["/app"]}>
        <Routes>
          <Route
            path="/app"
            element={
              <ProtectedRoute allowedRoles={["CUSTOMER"]}>
                <div>Customer Content</div>
              </ProtectedRoute>
            }
          />
          <Route path="/login" element={<div>Login Page Target</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.queryByText("Customer Content")).not.toBeInTheDocument();
    expect(screen.getByText("Login Page Target")).toBeInTheDocument();
  });

  it("denies access when user role is not allowed and redirects to role dashboard", () => {
    const customerUser: User = {
      id: "u-1",
      email: "customer@example.com",
      role: "CUSTOMER",
      is_active: true,
      created_at: new Date().toISOString(),
    };

    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      user: customerUser,
      token: "valid-token",
      isLoading: false,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
      refreshUser: vi.fn(),
    });

    render(
      <MemoryRouter initialEntries={["/admin/analytics"]}>
        <Routes>
          <Route
            path="/admin/analytics"
            element={
              <ProtectedRoute allowedRoles={["ADMIN"]}>
                <div>Admin Analytics</div>
              </ProtectedRoute>
            }
          />
          <Route path="/app" element={<div>Customer Dashboard Target</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.queryByText("Admin Analytics")).not.toBeInTheDocument();
    expect(screen.getByText("Customer Dashboard Target")).toBeInTheDocument();
  });

  it("renders protected content when role matches", () => {
    const agentUser: User = {
      id: "u-2",
      email: "agent@example.com",
      role: "SUPPORT_AGENT",
      is_active: true,
      created_at: new Date().toISOString(),
    };

    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      user: agentUser,
      token: "valid-token",
      isLoading: false,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
      refreshUser: vi.fn(),
    });

    render(
      <MemoryRouter initialEntries={["/agent"]}>
        <Routes>
          <Route
            path="/agent"
            element={
              <ProtectedRoute allowedRoles={["SUPPORT_AGENT", "ADMIN"]}>
                <div>Agent Workspace</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByText("Agent Workspace")).toBeInTheDocument();
  });

  it("renders login page with email and password inputs", () => {
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      user: null,
      token: null,
      isLoading: false,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
      refreshUser: vi.fn(),
    });

    const queryClient = createQueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <MemoryRouter>
            <LoginPage />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );

    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });
});
