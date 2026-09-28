/**
 * Agent Ticket List — /agent/tickets
 * Full ticket management view for agents and admins.
 */

import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { ticketsApi } from "@/services/api";
import {
  Card,
  StatusBadge,
  PriorityBadge,
  Select,
  Alert,
  EmptyState,
  Pagination,
} from "@/components/ui";
import { PageHeader } from "@/components/layout/PageHeader";
import { Ticket, TicketStatus, TicketPriority } from "@/types";
import { ChevronRight, Ticket as TicketIcon } from "lucide-react";

const STATUS_OPTIONS = [
  { value: "", label: "All Statuses" },
  { value: "OPEN", label: "Open" },
  { value: "AI_PROCESSING", label: "AI Processing" },
  { value: "PENDING_AGENT_REVIEW", label: "Pending Review" },
  { value: "IN_PROGRESS", label: "In Progress" },
  { value: "RESOLVED", label: "Resolved" },
  { value: "CLOSED", label: "Closed" },
];

const PRIORITY_OPTIONS = [
  { value: "", label: "All Priorities" },
  { value: "LOW", label: "Low" },
  { value: "MEDIUM", label: "Medium" },
  { value: "HIGH", label: "High" },
  { value: "URGENT", label: "Urgent" },
];

const PAGE_SIZE = 20;

export const AgentTicketListPage: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState<TicketStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<TicketPriority | "">("");
  const [offset, setOffset] = useState(0);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["tickets", "agent", statusFilter, priorityFilter, offset],
    queryFn: () =>
      ticketsApi.listTickets({
        limit: PAGE_SIZE,
        offset,
        status: statusFilter || undefined,
        priority: priorityFilter || undefined,
      }),
    placeholderData: keepPreviousData,
  });

  const tickets = data?.tickets || [];
  const total = data?.total || 0;

  return (
    <div className="px-6 py-8 max-w-6xl mx-auto">
      <PageHeader
        title="All Tickets"
        description="Manage and respond to support tickets across all customers."
      />

      {/* Filters */}
      <div className="flex items-center gap-3 mb-5 flex-wrap">
        <Select
          id="agent-filter-status"
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value as TicketStatus | "");
            setOffset(0);
          }}
          options={STATUS_OPTIONS}
          className="w-44"
        />
        <Select
          id="agent-filter-priority"
          value={priorityFilter}
          onChange={(e) => {
            setPriorityFilter(e.target.value as TicketPriority | "");
            setOffset(0);
          }}
          options={PRIORITY_OPTIONS}
          className="w-40"
        />
        {(statusFilter || priorityFilter) && (
          <button
            className="text-xs text-slate-500 hover:text-rose-600 font-medium"
            onClick={() => {
              setStatusFilter("");
              setPriorityFilter("");
              setOffset(0);
            }}
          >
            Clear filters
          </button>
        )}
        <span className="ml-auto text-xs text-slate-400">{total} tickets</span>
      </div>

      {isError && (
        <Alert variant="error" className="mb-4">
          Failed to load tickets.
        </Alert>
      )}

      <Card>
        {isLoading ? (
          <div className="p-6 space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-16 animate-pulse rounded-lg bg-slate-100" />
            ))}
          </div>
        ) : tickets.length === 0 ? (
          <EmptyState
            icon={<TicketIcon className="w-7 h-7" />}
            title="No tickets found"
            description="Try adjusting the filters."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    Ticket
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    Priority
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    Category
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    Created
                  </th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {tickets.map((ticket: Ticket) => (
                  <tr
                    key={ticket.id}
                    className="hover:bg-slate-50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <Link
                        to={`/agent/tickets/${ticket.id}`}
                        className="block"
                      >
                        <p className="font-medium text-slate-900 truncate max-w-xs">
                          {ticket.title}
                        </p>
                        <p className="text-xs text-slate-400 mt-0.5 font-mono">
                          #{ticket.ticket_number}
                        </p>
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={ticket.status} />
                    </td>
                    <td className="px-4 py-3">
                      <PriorityBadge priority={ticket.priority} />
                    </td>
                    <td className="px-4 py-3 text-slate-500 text-xs">
                      {ticket.category || "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">
                      {new Date(ticket.created_at).toLocaleDateString("en-US", {
                        year: "numeric",
                        month: "short",
                        day: "numeric",
                      })}
                    </td>
                    <td className="px-4 py-3">
                      <Link to={`/agent/tickets/${ticket.id}`}>
                        <ChevronRight className="w-4 h-4 text-slate-300" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {total > PAGE_SIZE && (
        <Pagination
          total={total}
          offset={offset}
          limit={PAGE_SIZE}
          onPageChange={setOffset}
          className="mt-4"
        />
      )}
    </div>
  );
};
