/**
 * Admin Analytics Dashboard — /admin/analytics
 * Operational metrics and trends for administrators.
 * Renders only the fields that the backend AnalyticsSummaryResponse actually returns.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { analyticsApi } from "@/services/api";
import {
  Card,
  CardContent,
  CardSkeleton,
  Alert,
  Badge,
} from "@/components/ui";
import { PageHeader } from "@/components/layout/PageHeader";
import { AnalyticsSummary } from "@/types";
import {
  Ticket,
  CheckCircle2,
  TrendingUp,
  ClipboardList,
  Bot,
  XCircle,
  BarChart3,
} from "lucide-react";

interface MetricCardProps {
  label: string;
  value: number | string;
  subLabel?: string;
  icon: React.ReactNode;
  bg: string;
}

const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  subLabel,
  icon,
  bg,
}) => (
  <Card>
    <CardContent className="pt-5">
      <div className="flex items-start justify-between">
        <div className={`rounded-xl p-2.5 ${bg}`}>{icon}</div>
      </div>
      <div className="mt-4">
        <p className="text-2xl font-bold text-slate-900">{value}</p>
        <p className="text-sm font-medium text-slate-700">{label}</p>
        {subLabel && <p className="text-xs text-slate-400 mt-0.5">{subLabel}</p>}
      </div>
    </CardContent>
  </Card>
);

/** Format confidence score (0.0–1.0) as percentage string */
const formatPct = (n?: number | null): string =>
  n != null ? `${Math.round(n * 100)}%` : "—";

/** Bar chart row for breakdown tables */
const BreakdownRow: React.FC<{
  label: string;
  count: number;
  total: number;
  color?: string;
}> = ({ label, count, total, color = "bg-brand-500" }) => {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <p className="w-44 text-sm text-slate-600 shrink-0 capitalize">
        {label.replace(/_/g, " ").toLowerCase()}
      </p>
      <div className="flex-1 bg-slate-100 rounded-full h-2 overflow-hidden">
        <div
          className={`${color} h-2 rounded-full transition-all duration-700`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="w-16 text-right text-xs font-medium text-slate-600">
        {count} <span className="text-slate-400">({pct}%)</span>
      </p>
    </div>
  );
};

export const AnalyticsDashboardPage: React.FC = () => {
  const { data, isLoading, isError } = useQuery<AnalyticsSummary>({
    queryKey: ["analytics", "summary"],
    queryFn: () => analyticsApi.getSummary(),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const totalTickets = data?.total_tickets ?? 0;
  const totalReviews = data?.total_reviews ?? 0;

  return (
    <div className="px-6 py-8 max-w-6xl mx-auto">
      <PageHeader
        title="Analytics Dashboard"
        description="Real-time operational metrics for your support operations."
        actions={
          <Badge variant="secondary" className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            Live
          </Badge>
        }
      />

      {isError && (
        <Alert variant="error" className="mb-6">
          Failed to load analytics. Please refresh.
        </Alert>
      )}

      {/* Ticket overview */}
      <div className="mb-2">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Ticket Overview
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {isLoading ? (
            <>
              <CardSkeleton />
              <CardSkeleton />
              <CardSkeleton />
              <CardSkeleton />
            </>
          ) : (
            <>
              <MetricCard
                label="Total Tickets"
                value={data?.total_tickets ?? "—"}
                icon={<Ticket className="w-5 h-5 text-sky-600" />}
                bg="bg-sky-50"
              />
              <MetricCard
                label="Open Tickets"
                value={data?.open_tickets ?? "—"}
                icon={<TrendingUp className="w-5 h-5 text-amber-600" />}
                bg="bg-amber-50"
              />
              <MetricCard
                label="Resolved"
                value={data?.resolved_tickets ?? "—"}
                icon={<CheckCircle2 className="w-5 h-5 text-emerald-600" />}
                bg="bg-emerald-50"
              />
              <MetricCard
                label="Closed"
                value={data?.closed_tickets ?? "—"}
                icon={<XCircle className="w-5 h-5 text-slate-500" />}
                bg="bg-slate-100"
              />
            </>
          )}
        </div>
      </div>

      {/* AI & Review metrics */}
      <div className="mb-2">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          AI & Review Queue
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {isLoading ? (
            <>
              <CardSkeleton />
              <CardSkeleton />
              <CardSkeleton />
              <CardSkeleton />
            </>
          ) : (
            <>
              <MetricCard
                label="Total AI Runs"
                value={data?.total_ai_runs ?? "—"}
                subLabel="Agent orchestration executions"
                icon={<Bot className="w-5 h-5 text-brand-600" />}
                bg="bg-brand-50"
              />
              <MetricCard
                label="Avg. Confidence"
                value={formatPct(data?.average_confidence)}
                subLabel="Across AI responses"
                icon={<BarChart3 className="w-5 h-5 text-purple-600" />}
                bg="bg-purple-50"
              />
              <MetricCard
                label="Pending Reviews"
                value={data?.pending_reviews ?? "—"}
                subLabel="Awaiting agent decision"
                icon={<ClipboardList className="w-5 h-5 text-orange-600" />}
                bg="bg-orange-50"
              />
              <MetricCard
                label="Completed Reviews"
                value={data?.completed_reviews ?? "—"}
                subLabel="Reviewed and actioned"
                icon={<CheckCircle2 className="w-5 h-5 text-teal-600" />}
                bg="bg-teal-50"
              />
            </>
          )}
        </div>
      </div>

      {/* Status breakdown */}
      {!isLoading && data?.tickets_by_status && Object.keys(data.tickets_by_status).length > 0 && (
        <div className="mb-6">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Tickets by Status
          </h2>
          <Card>
            <CardContent className="pt-5 space-y-3">
              {Object.entries(data.tickets_by_status)
                .sort(([, a], [, b]) => b - a)
                .map(([status, count]) => (
                  <BreakdownRow
                    key={status}
                    label={status}
                    count={count}
                    total={totalTickets}
                    color="bg-brand-500"
                  />
                ))}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Category breakdown */}
      {!isLoading && data?.tickets_by_category && Object.keys(data.tickets_by_category).length > 0 && (
        <div className="mb-6">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Tickets by Category
          </h2>
          <Card>
            <CardContent className="pt-5 space-y-3">
              {Object.entries(data.tickets_by_category)
                .sort(([, a], [, b]) => b - a)
                .map(([category, count]) => (
                  <BreakdownRow
                    key={category}
                    label={category}
                    count={count}
                    total={totalTickets}
                    color="bg-sky-500"
                  />
                ))}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Priority breakdown */}
      {!isLoading && data?.tickets_by_priority && Object.keys(data.tickets_by_priority).length > 0 && (
        <div className="mb-6">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Tickets by Priority
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {Object.entries(data.tickets_by_priority).map(([priority, count]) => (
              <Card key={priority}>
                <CardContent className="text-center pt-5">
                  <p className="text-3xl font-bold text-slate-900">{count}</p>
                  <p className="text-sm text-slate-500 mt-1 capitalize">
                    {priority.toLowerCase()}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Reviews by status */}
      {!isLoading && data?.reviews_by_status && Object.keys(data.reviews_by_status).length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Reviews by Status
          </h2>
          <Card>
            <CardContent className="pt-5 space-y-3">
              {Object.entries(data.reviews_by_status)
                .sort(([, a], [, b]) => b - a)
                .map(([status, count]) => (
                  <BreakdownRow
                    key={status}
                    label={status}
                    count={count}
                    total={totalReviews}
                    color="bg-purple-500"
                  />
                ))}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
};
