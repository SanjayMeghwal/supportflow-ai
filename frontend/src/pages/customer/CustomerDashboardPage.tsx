/**
 * Customer Dashboard — /app
 * Shows summary stats and recent tickets for the authenticated customer.
 */

import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ticketsApi } from "@/services/api";
import { useAuth } from "@/context/AuthContext";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardSkeleton,
  StatusBadge,
  PriorityBadge,
  Button,
  Alert,
  EmptyState,
} from "@/components/ui";
import { PageHeader } from "@/components/layout/PageHeader";
import { Ticket as TicketType } from "@/types";
import {
  Ticket,
  CheckCircle2,
  Clock,
  PlusCircle,
  ChevronRight,
} from "lucide-react";

interface StatCardProps {
  label: string;
  value: number;
  icon: React.ReactNode;
  color: string;
}

const StatCard: React.FC<StatCardProps> = ({ label, value, icon, color }) => (
  <Card>
    <CardContent className="flex items-center gap-4">
      <div className={`rounded-xl p-2.5 ${color}`}>{icon}</div>
      <div>
        <p className="text-2xl font-bold text-slate-900">{value}</p>
        <p className="text-sm text-slate-500">{label}</p>
      </div>
    </CardContent>
  </Card>
);

export const CustomerDashboardPage: React.FC = () => {
  const { user } = useAuth();
  const navigate = useNavigate();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["tickets", "customer-dashboard"],
    queryFn: () => ticketsApi.listTickets({ limit: 10, offset: 0 }),
  });

  const tickets = data?.tickets || [];
  const total = data?.total || 0;

  const openCount = tickets.filter((t) => t.status === "OPEN").length;
  const resolvedCount = tickets.filter(
    (t) => t.status === "RESOLVED" || t.status === "CLOSED"
  ).length;
  const pendingCount = tickets.filter(
    (t) =>
      t.status === "IN_PROGRESS" ||
      t.status === "PENDING_AGENT_REVIEW" ||
      t.status === "AI_PROCESSING"
  ).length;

  return (
    <div className="px-6 py-8 max-w-5xl mx-auto">
      <PageHeader
        title={`Welcome back${user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}!`}
        description="Here's a summary of your support activity."
        actions={
          <Link to="/app/tickets/new">
            <Button
              id="dashboard-create-ticket"
              size="sm"
              leftIcon={<PlusCircle className="w-4 h-4" />}
            >
              New Ticket
            </Button>
          </Link>
        }
      />

      {isError && (
        <Alert variant="error" className="mb-6">
          Could not load your ticket summary. Please refresh.
        </Alert>
      )}

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        {isLoading ? (
          <>
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </>
        ) : (
          <>
            <StatCard
              label="Open Tickets"
              value={openCount}
              icon={<Ticket className="w-5 h-5 text-sky-600" />}
              color="bg-sky-50"
            />
            <StatCard
              label="In Progress"
              value={pendingCount}
              icon={<Clock className="w-5 h-5 text-amber-600" />}
              color="bg-amber-50"
            />
            <StatCard
              label="Resolved"
              value={resolvedCount}
              icon={<CheckCircle2 className="w-5 h-5 text-emerald-600" />}
              color="bg-emerald-50"
            />
          </>
        )}
      </div>

      {/* Recent tickets */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Tickets</CardTitle>
          {total > 5 && (
            <Link
              to="/app/tickets"
              className="text-sm text-brand-600 hover:text-brand-700 font-medium flex items-center gap-1"
            >
              View all <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          )}
        </CardHeader>

        {isLoading ? (
          <div className="p-6 space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-14 animate-pulse rounded-lg bg-slate-100" />
            ))}
          </div>
        ) : tickets.length === 0 ? (
          <EmptyState
            icon={<Ticket className="w-7 h-7" />}
            title="No tickets yet"
            description="When you create a support ticket, it will appear here."
            action={{
              label: "Create your first ticket",
              onClick: () => navigate("/app/tickets/new"),
            }}
          />
        ) : (
          <div className="divide-y divide-slate-100">
            {tickets.slice(0, 5).map((ticket: TicketType) => (
              <Link
                key={ticket.id}
                to={`/app/tickets/${ticket.id}`}
                className="flex items-center gap-4 px-6 py-3.5 hover:bg-slate-50 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-900 truncate">
                    {ticket.title}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {ticket.ticket_number} ·{" "}
                    {new Date(ticket.created_at).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                    })}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <PriorityBadge priority={ticket.priority} />
                  <StatusBadge status={ticket.status} />
                </div>
                <ChevronRight className="w-4 h-4 text-slate-300 shrink-0" />
              </Link>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};
