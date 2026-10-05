/**
 * SupportFlow AI — Application Router
 * Defines all routes with role-based protection and lazy-loading.
 */

import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
import { ProtectedRoute } from "@/components/layout/ProtectedRoute";

// Auth pages
import { LoginPage } from "@/pages/LoginPage";
import { RegisterPage } from "@/pages/RegisterPage";

// Customer pages
import { CustomerDashboardPage } from "@/pages/customer/CustomerDashboardPage";
import { CustomerTicketListPage } from "@/pages/customer/CustomerTicketListPage";
import { CustomerTicketDetailPage } from "@/pages/customer/CustomerTicketDetailPage";
import { CreateTicketPage } from "@/pages/customer/CreateTicketPage";

// Agent pages
import { AgentDashboardPage } from "@/pages/agent/AgentDashboardPage";
import { AgentTicketListPage } from "@/pages/agent/AgentTicketListPage";
import { AgentTicketDetailPage } from "@/pages/agent/AgentTicketDetailPage";
import { ReviewQueuePage } from "@/pages/agent/ReviewQueuePage";
import { KnowledgeBasePage } from "@/pages/agent/KnowledgeBasePage";

// Admin pages
import { AnalyticsDashboardPage } from "@/pages/admin/AnalyticsDashboardPage";

// Shared Demo pages
import { AIAssistantPage } from "@/pages/shared/AIAssistantPage";
import { ArchitecturePage } from "@/pages/shared/ArchitecturePage";

export const App: React.FC = () => {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      {/* Customer portal — CUSTOMER role */}
      <Route
        path="/app"
        element={
          <ProtectedRoute allowedRoles={["CUSTOMER"]}>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<CustomerDashboardPage />} />
        <Route path="tickets" element={<CustomerTicketListPage />} />
        <Route path="tickets/new" element={<CreateTicketPage />} />
        <Route path="tickets/:id" element={<CustomerTicketDetailPage />} />
        <Route path="assistant" element={<AIAssistantPage />} />
        <Route path="architecture" element={<ArchitecturePage />} />
      </Route>

      {/* Agent/Admin portal — SUPPORT_AGENT + ADMIN roles */}
      <Route
        path="/agent"
        element={
          <ProtectedRoute allowedRoles={["SUPPORT_AGENT", "ADMIN"]}>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<AgentDashboardPage />} />
        <Route path="tickets" element={<AgentTicketListPage />} />
        <Route path="tickets/:id" element={<AgentTicketDetailPage />} />
        <Route path="reviews" element={<ReviewQueuePage />} />
        <Route path="knowledge" element={<KnowledgeBasePage />} />
        <Route path="assistant" element={<AIAssistantPage />} />
        <Route path="architecture" element={<ArchitecturePage />} />
      </Route>

      {/* Admin-only routes */}
      <Route
        path="/admin"
        element={
          <ProtectedRoute allowedRoles={["ADMIN"]}>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="analytics" element={<AnalyticsDashboardPage />} />
      </Route>

      {/* Root redirect */}
      <Route path="/" element={<Navigate to="/login" replace />} />

      {/* 404 catch-all */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
};

