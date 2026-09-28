/**
 * Agent Dashboard — /agent
 * Overview metrics for agents and admins.
 */

import React from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ticketsApi, reviewsApi } from "@/services/api";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardSkeleton,
  StatusBadge,
  PriorityBadge,
  Alert,
  EmptyState,
} from "@/components/ui";
import { PageHeader } from "@/components/layout/PageHeader";
import { useAuth } from "@/context/AuthContext";
import {
  Ticket,
  ClipboardList,
  TrendingUp,
  ChevronRight,
  AlertTriangle,
} from "lucide-react";
import { Ticket as TicketType } from "@/types";

const StatCard: React.FC<{
  label: string;
  value: number | string;
  icon: React.ReactNode;
  bg: string;
  to?: string;
}> = ({ label, value, icon, bg, to }) => {
  const content = (
    <Card className={to ? "hover:shadow-md transition-shadow cursor-pointer" : ""}>
      <CardContent className="flex items-center gap-4">
        <div className={`rounded-xl p-2.5 ${bg}`}>{icon}</div>
        <div>
          <p className="text-2xl font-bold text-slate-900">{value}</p>
          <p className="text-sm text-slate-500">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
  return to ? <Link to={to}>{content}</Link> : content;
};

export const AgentDashboardPage: React.FC = () => {
  const { user } = useAuth();

  const { data: ticketData, isLoading: ticketLoading, isError: ticketError } = useQuery({
    queryKey: ["tickets", "agent-dashboard"],
    queryFn: () => ticketsApi.listTickets({ limit: 100, offset: 0 }),
  });

  const { data: reviewData, isLoading: reviewLoading, isError: reviewError } = useQuery({
    queryKey: ["reviews", "agent-dashboard"],
    queryFn: () => reviewsApi.listReviews({ limit: 100 }),
  });

  const tickets = ticketData?.tickets || [];
  const totalTickets = ticketData?.total || 0;
  const pendingReviews = reviewData?.total || 0;
  const openTickets = tickets.filter((t) => t.status === "OPEN").length;
  const criticalTickets = tickets.filter(
    (t) => t.priority === "URGENT" && t.status !== "CLOSED" && t.status !== "RESOLVED"
  );
  const recentTickets = tickets.slice(0, 6);

  return (
    <div className="px-6 py-8 max-w-6xl mx-auto">
      <PageHeader
        title={`${user?.role === "ADMIN" ? "Admin" : "Agent"} Dashboard`}
        description="Real-time overview of ticket operations and review queue."
      />

      {(ticketError || reviewError) && (
        <Alert variant="error" className="mb-6">
          Some data could not be loaded. Try refreshing.
        </Alert>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {ticketLoading || reviewLoading ? (
          <>
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </>
        ) : (
          <>
            <StatCard
              label="Total Tickets"
              value={totalTickets}
              icon={<Ticket className="w-5 h-5 text-sky-600" />}
              bg="bg-sky-50"
              to="/agent/tickets"
            />
            <StatCard
              label="Open"
              value={openTickets}
              icon={<TrendingUp className="w-5 h-5 text-amber-600" />}
              bg="bg-amber-50"
            />
            <StatCard
              label="Pending Reviews"
              value={pendingReviews}
              icon={<ClipboardList className="w-5 h-5 text-purple-600" />}
              bg="bg-purple-50"
              to="/agent/reviews"
            />
            <StatCard
              label="Critical Issues"
              value={criticalTickets.length}
              icon={<AlertTriangle className="w-5 h-5 text-rose-600" />}
              bg="bg-rose-50"
            />
          </>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent tickets */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Recent Tickets</CardTitle>
              <Link
                to="/agent/tickets"
                className="text-sm text-brand-600 hover:text-brand-700 font-medium flex items-center gap-1"
              >
                View all <ChevronRight className="w-3.5 h-3.5" />
              </Link>
            </CardHeader>
            {ticketLoading ? (
              <div className="p-6 space-y-3">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-14 animate-pulse rounded-lg bg-slate-100" />
                ))}
              </div>
            ) : recentTickets.length === 0 ? (
              <EmptyState
                icon={<Ticket className="w-6 h-6" />}
                title="No tickets yet"
              />
            ) : (
              <div className="divide-y divide-slate-100">
                {recentTickets.map((ticket: TicketType) => (
                  <Link
                    key={ticket.id}
                    to={`/agent/tickets/${ticket.id}`}
                    className="flex items-center gap-4 px-6 py-3.5 hover:bg-slate-50 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-900 truncate">
                        {ticket.title}
                      </p>
                      <p className="text-xs text-slate-400 mt-0.5">
                        #{ticket.ticket_number} ·{" "}
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
                    <ChevronRight className="w-4 h-4 text-slate-300" />
                  </Link>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Critical tickets */}
        <div>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-rose-500" />
                Critical
              </CardTitle>
            </CardHeader>
            {ticketLoading ? (
              <div className="p-6 space-y-3">
                {[1, 2].map((i) => (
                  <div key={i} className="h-12 animate-pulse rounded-lg bg-slate-100" />
                ))}
              </div>
            ) : criticalTickets.length === 0 ? (
              <EmptyState title="No critical tickets" className="py-10" />
            ) : (
              <div className="divide-y divide-slate-100">
                {criticalTickets.slice(0, 5).map((ticket: TicketType) => (
                  <Link
                    key={ticket.id}
                    to={`/agent/tickets/${ticket.id}`}
                    className="flex items-center gap-3 px-5 py-3 hover:bg-slate-50 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-900 truncate">
                        {ticket.title}
                      </p>
                      <StatusBadge status={ticket.status} size="sm" />
                    </div>
                    <ChevronRight className="w-4 h-4 text-slate-300" />
                  </Link>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
};
