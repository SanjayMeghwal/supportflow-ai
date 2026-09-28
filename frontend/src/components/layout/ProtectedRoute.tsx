/**
 * Protected route guards for authentication and RBAC.
 * Frontend guards are UX-only — backend enforces actual authorization.
 */

import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Spinner } from "@/components/ui";
import { UserRole } from "@/types";

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredRoles?: UserRole[];
  allowedRoles?: UserRole[];
  redirectTo?: string;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  requiredRoles,
  allowedRoles,
  redirectTo = "/login",
}) => {
  // allowedRoles is an alias for requiredRoles
  const roles = allowedRoles ?? requiredRoles;
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-50">
        <Spinner size="lg" className="text-brand-600" />
      </div>
    );
  }

  if (!user) {
    return <Navigate to={redirectTo} state={{ from: location }} replace />;
  }

  if (roles && !roles.includes(user.role)) {
    // Redirect to appropriate home for their role
    const roleHome = getRoleHome(user.role);
    return <Navigate to={roleHome} replace />;
  }

  return <>{children}</>;
};

function getRoleHome(role: UserRole): string {
  switch (role) {
    case "ADMIN":
      return "/agent";
    case "SUPPORT_AGENT":
      return "/agent";
    case "CUSTOMER":
      return "/app";
    default:
      return "/login";
  }
}

export const GuestRoute: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-50">
        <Spinner size="lg" className="text-brand-600" />
      </div>
    );
  }

  if (user) {
    return <Navigate to={getRoleHome(user.role)} replace />;
  }

  return <>{children}</>;
};
