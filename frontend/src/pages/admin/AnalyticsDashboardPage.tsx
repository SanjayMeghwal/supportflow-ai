/**
 * Admin Analytics Dashboard — /admin/analytics
 * Operational metrics, system observability, request latency percentiles, and LLM token analytics.
 */

import React, { useState } from "react";
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
import {
  AnalyticsSummary,
  LLMAnalyticsSummary,
  ObservabilityOverview,
} from "@/types";
import {
  Ticket,
  CheckCircle2,
  TrendingUp,
  ClipboardList,
  Bot,
  XCircle,
  BarChart3,
  Activity,
  Zap,
  Clock,
  Coins,
  Cpu,
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
  const [period, setPeriod] = useState<string>("24h");

  // Operational metrics
  const {
    data: opsData,
    isLoading: isOpsLoading,
    isError: isOpsError,
  } = useQuery<AnalyticsSummary>({
    queryKey: ["analytics", "summary"],
    queryFn: () => analyticsApi.getSummary(),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // System Observability Overview
  const {
    data: obsData,
    isLoading: isObsLoading,
  } = useQuery<ObservabilityOverview>({
    queryKey: ["analytics", "observability", "overview"],
    queryFn: () => analyticsApi.getObservabilityOverview(),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  // LLM Token Analytics
  const {
    data: llmData,
    isLoading: isLlmLoading,
  } = useQuery<LLMAnalyticsSummary>({
    queryKey: ["analytics", "observability", "llm", period],
    queryFn: () => analyticsApi.getLLMAnalytics(period),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const totalTickets = opsData?.total_tickets ?? 0;
  const totalReviews = opsData?.total_reviews ?? 0;

  return (
    <div className="px-6 py-8 max-w-6xl mx-auto">
      <PageHeader
        title="Analytics Dashboard"
        description="Real-time operational metrics, system observability, and AI token analytics."
        actions={
          <div className="flex items-center gap-2">
            <div className="flex bg-slate-100 rounded-lg p-0.5 text-xs font-medium">
              {["1h", "24h", "7d", "30d"].map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  className={`px-2.5 py-1 rounded-md transition-colors ${
                    period === p
                      ? "bg-white text-slate-900 shadow-sm font-semibold"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
            <Badge variant="secondary" className="flex items-center gap-1.5 ml-2">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Live
            </Badge>
          </div>
        }
      />

      {isOpsError && (
        <Alert variant="error" className="mb-6">
          Failed to load analytics. Please refresh.
        </Alert>
      )}

      {/* Observability & System Latency */}
      <div className="mb-8">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          System Observability & Request Latencies
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {isObsLoading ? (
            <>
              <CardSkeleton />
              <CardSkeleton />
              <CardSkeleton />
              <CardSkeleton />
            </>
          ) : (
            <>
              <MetricCard
                label="Total HTTP Requests"
                value={obsData?.requests.total_requests ?? 0}
                subLabel={`Error rate: ${((obsData?.requests.error_rate ?? 0) * 100).toFixed(1)}%`}
                icon={<Activity className="w-5 h-5 text-indigo-600" />}
                bg="bg-indigo-50"
              />
              <MetricCard
                label="p50 Latency"
                value={`${obsData?.requests.p50_latency_ms ?? 0} ms`}
                subLabel="Median response time"
                icon={<Clock className="w-5 h-5 text-emerald-600" />}
                bg="bg-emerald-50"
              />
              <MetricCard
                label="p95 Latency"
                value={`${obsData?.requests.p95_latency_ms ?? 0} ms`}
                subLabel="95th percentile response time"
                icon={<Zap className="w-5 h-5 text-amber-600" />}
                bg="bg-amber-50"
              />
              <MetricCard
                label="p99 Latency"
                value={`${obsData?.requests.p99_latency_ms ?? 0} ms`}
                subLabel="99th percentile response time"
                icon={<TrendingUp className="w-5 h-5 text-rose-600" />}
                bg="bg-rose-50"
              />
            </>
          )}
        </div>
      </div>

      {/* AI Token & Model Telemetry */}
      <div className="mb-8">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          AI Token Telemetry & LLM Analytics ({period})
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
          {isLlmLoading ? (
            <>
              <CardSkeleton />
              <CardSkeleton />
              <CardSkeleton />
              <CardSkeleton />
            </>
          ) : (
            <>
              <MetricCard
                label="Total LLM Calls"
                value={llmData?.total_calls ?? 0}
                subLabel={`Success: ${llmData?.success_count ?? 0} | Failures: ${llmData?.failure_count ?? 0}`}
                icon={<Cpu className="w-5 h-5 text-violet-600" />}
                bg="bg-violet-50"
              />
              <MetricCard
                label="Total Tokens Consumed"
                value={(llmData?.tokens.total ?? 0).toLocaleString()}
                subLabel={`Prompt: ${(llmData?.tokens.prompt ?? 0).toLocaleString()} | Completion: ${(llmData?.tokens.completion ?? 0).toLocaleString()}`}
                icon={<Coins className="w-5 h-5 text-amber-600" />}
                bg="bg-amber-50"
              />
              <MetricCard
                label="Avg. LLM Latency"
                value={`${llmData?.avg_latency_ms ?? 0} ms`}
                subLabel="Per inference completion"
                icon={<Clock className="w-5 h-5 text-blue-600" />}
                bg="bg-blue-50"
              />
              <MetricCard
                label="LLM Error Rate"
                value={`${((llmData?.error_rate ?? 0) * 100).toFixed(1)}%`}
                subLabel="Provider failure rate"
                icon={<XCircle className="w-5 h-5 text-rose-600" />}
                bg="bg-rose-50"
              />
            </>
          )}
        </div>

        {/* Model Usage Breakdown */}
        {!isLlmLoading && llmData?.models && Object.keys(llmData.models).length > 0 && (
          <Card className="mb-6">
            <CardContent className="pt-5">
              <h3 className="text-sm font-semibold text-slate-800 mb-3">
                Token Consumption by Model
              </h3>
              <div className="space-y-3">
                {Object.entries(llmData.models).map(([modelName, stat]) => (
                  <div key={modelName} className="flex items-center justify-between text-sm py-1 border-b border-slate-100 last:border-0">
                    <span className="font-mono text-xs text-slate-700 font-medium">
                      {modelName}
                    </span>
                    <div className="flex items-center gap-6 text-xs text-slate-600">
                      <span><strong>{stat.calls}</strong> calls</span>
                      <span><strong>{stat.tokens.toLocaleString()}</strong> tokens</span>
                      <span><strong>{stat.avg_latency_ms}</strong> ms avg</span>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Ticket overview */}
      <div className="mb-2">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Ticket Overview
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {isOpsLoading ? (
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
                value={opsData?.total_tickets ?? "—"}
                icon={<Ticket className="w-5 h-5 text-sky-600" />}
                bg="bg-sky-50"
              />
              <MetricCard
                label="Open Tickets"
                value={opsData?.open_tickets ?? "—"}
                icon={<TrendingUp className="w-5 h-5 text-amber-600" />}
                bg="bg-amber-50"
              />
              <MetricCard
                label="Resolved"
                value={opsData?.resolved_tickets ?? "—"}
                icon={<CheckCircle2 className="w-5 h-5 text-emerald-600" />}
                bg="bg-emerald-50"
              />
              <MetricCard
                label="Closed"
                value={opsData?.closed_tickets ?? "—"}
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
          {isOpsLoading ? (
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
                value={opsData?.total_ai_runs ?? "—"}
                subLabel="Agent orchestration executions"
                icon={<Bot className="w-5 h-5 text-brand-600" />}
                bg="bg-brand-50"
              />
              <MetricCard
                label="Avg. Confidence"
                value={formatPct(opsData?.average_confidence)}
                subLabel="Across AI responses"
                icon={<BarChart3 className="w-5 h-5 text-purple-600" />}
                bg="bg-purple-50"
              />
              <MetricCard
                label="Pending Reviews"
                value={opsData?.pending_reviews ?? "—"}
                subLabel="Awaiting agent decision"
                icon={<ClipboardList className="w-5 h-5 text-orange-600" />}
                bg="bg-orange-50"
              />
              <MetricCard
                label="Completed Reviews"
                value={opsData?.completed_reviews ?? "—"}
                subLabel="Reviewed and actioned"
                icon={<CheckCircle2 className="w-5 h-5 text-teal-600" />}
                bg="bg-teal-50"
              />
            </>
          )}
        </div>
      </div>

      {/* Status breakdown */}
      {!isOpsLoading && opsData?.tickets_by_status && Object.keys(opsData.tickets_by_status).length > 0 && (
        <div className="mb-6">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Tickets by Status
          </h2>
          <Card>
            <CardContent className="pt-5 space-y-3">
              {Object.entries(opsData.tickets_by_status)
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
      {!isOpsLoading && opsData?.tickets_by_category && Object.keys(opsData.tickets_by_category).length > 0 && (
        <div className="mb-6">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Tickets by Category
          </h2>
          <Card>
            <CardContent className="pt-5 space-y-3">
              {Object.entries(opsData.tickets_by_category)
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
      {!isOpsLoading && opsData?.tickets_by_priority && Object.keys(opsData.tickets_by_priority).length > 0 && (
        <div className="mb-6">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Tickets by Priority
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {Object.entries(opsData.tickets_by_priority).map(([priority, count]) => (
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
      {!isOpsLoading && opsData?.reviews_by_status && Object.keys(opsData.reviews_by_status).length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Reviews by Status
          </h2>
          <Card>
            <CardContent className="pt-5 space-y-3">
              {Object.entries(opsData.reviews_by_status)
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
