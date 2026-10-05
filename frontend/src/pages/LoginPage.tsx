/**
 * Login Page — /login
 */

import React, { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Button, Input, Alert } from "@/components/ui";
import { APIError } from "@/types";
import { Zap } from "lucide-react";

export const LoginPage: React.FC = () => {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const from = (location.state as { from?: Location })?.from?.pathname || null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    try {
      const user = await login({ email: email.trim().toLowerCase(), password });
      // Redirect based on role
      if (from) {
        navigate(from, { replace: true });
      } else if (user.role === "CUSTOMER") {
        navigate("/app", { replace: true });
      } else {
        navigate("/agent", { replace: true });
      }
    } catch (err) {
      if (err instanceof APIError) {
        setError(err.message);
      } else {
        setError("Unable to sign in. Please try again.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleDemoLogin = async (demoEmail: string, demoPass: string) => {
    setEmail(demoEmail);
    setPassword(demoPass);
    setError(null);
    setIsLoading(true);

    try {
      const user = await login({ email: demoEmail, password: demoPass });
      if (from) {
        navigate(from, { replace: true });
      } else if (user.role === "CUSTOMER") {
        navigate("/app", { replace: true });
      } else if (user.role === "ADMIN") {
        navigate("/admin/analytics", { replace: true });
      } else {
        navigate("/agent", { replace: true });
      }
    } catch (err) {
      if (err instanceof APIError) {
        setError(err.message);
      } else {
        setError("Unable to sign in. Please verify demo seed data is loaded.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-slate-100 to-brand-50/30 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo & Headline */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-brand-600 text-white shadow-md mb-3">
            <Zap className="w-6 h-6" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">SupportFlow AI</h1>
          <p className="text-xs text-slate-500 mt-1 max-w-xs mx-auto">
            Production-oriented AI customer-support and operations platform
          </p>
        </div>

        {/* Demo Roles Quick Login Card */}
        <div className="bg-white/90 backdrop-blur-sm rounded-2xl border border-brand-100 shadow-sm p-5 mb-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-bold uppercase tracking-wider text-brand-700">
              Interactive Portfolio Demo
            </span>
            <span className="text-[10px] font-medium bg-brand-50 text-brand-600 px-2 py-0.5 rounded-full border border-brand-200">
              Real JWT + RBAC
            </span>
          </div>
          <p className="text-xs text-slate-600 mb-3">
            Select a demo role to authenticate via standard JWT credentials:
          </p>
          <div className="grid grid-cols-3 gap-2">
            <button
              id="demo-login-customer"
              type="button"
              disabled={isLoading}
              onClick={() => handleDemoLogin("demo.customer@example.com", "DemoCustomer123!")}
              className="flex flex-col items-center text-center p-2.5 rounded-xl border border-slate-200 bg-slate-50/70 hover:bg-brand-50 hover:border-brand-300 transition-all text-xs group"
            >
              <span className="font-semibold text-slate-800 group-hover:text-brand-700">Customer</span>
              <span className="text-[10px] text-slate-500 mt-0.5">Alice Johnson</span>
              <span className="text-[9px] text-brand-600 font-mono mt-1">/app</span>
            </button>
            <button
              id="demo-login-agent"
              type="button"
              disabled={isLoading}
              onClick={() => handleDemoLogin("demo.agent@example.com", "DemoAgent123!")}
              className="flex flex-col items-center text-center p-2.5 rounded-xl border border-slate-200 bg-slate-50/70 hover:bg-brand-50 hover:border-brand-300 transition-all text-xs group"
            >
              <span className="font-semibold text-slate-800 group-hover:text-brand-700">Agent</span>
              <span className="text-[10px] text-slate-500 mt-0.5">Triage & HITL</span>
              <span className="text-[9px] text-brand-600 font-mono mt-1">/agent</span>
            </button>
            <button
              id="demo-login-admin"
              type="button"
              disabled={isLoading}
              onClick={() => handleDemoLogin("demo.admin@example.com", "DemoAdmin123!")}
              className="flex flex-col items-center text-center p-2.5 rounded-xl border border-slate-200 bg-slate-50/70 hover:bg-brand-50 hover:border-brand-300 transition-all text-xs group"
            >
              <span className="font-semibold text-slate-800 group-hover:text-brand-700">Admin</span>
              <span className="text-[10px] text-slate-500 mt-0.5">Metrics & Tokens</span>
              <span className="text-[9px] text-brand-600 font-mono mt-1">/admin</span>
            </button>
          </div>
        </div>

        {/* Standard Credentials Sign In */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 sm:p-7">
          <div className="mb-5">
            <h2 className="text-base font-bold text-slate-900">Sign in with credentials</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Enter email and password to test manual authentication.
            </p>
          </div>

          {error && (
            <Alert variant="error" className="mb-4">
              {error}
            </Alert>
          )}

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <Input
              id="login-email"
              label="Email address"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
            />
            <Input
              id="login-password"
              label="Password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
            <Button
              id="login-submit"
              type="submit"
              className="w-full mt-2"
              isLoading={isLoading}
              disabled={!email || !password}
            >
              {isLoading ? "Signing in…" : "Sign in"}
            </Button>
          </form>

          <p className="mt-5 text-center text-xs text-slate-500">
            Don't have an account?{" "}
            <Link
              to="/register"
              className="font-medium text-brand-600 hover:text-brand-700"
            >
              Create customer account
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
};

