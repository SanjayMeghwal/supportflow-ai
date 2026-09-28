/**
 * Customer Ticket List — /app/tickets
 * Displays all tickets belonging to the authenticated customer with filtering.
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
  Button,
  Alert,
  EmptyState,
  Pagination,
} from "@/components/ui";
import { PageHeader } from "@/components/layout/PageHeader";
import { Ticket, TicketStatus, TicketPriority } from "@/types";
import { PlusCircle, ChevronRight, Ticket as TicketIcon } from "lucide-react";

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

const PAGE_SIZE = 15;

export const CustomerTicketListPage: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState<TicketStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<TicketPriority | "">("");
  const [offset, setOffset] = useState(0);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["tickets", "customer", statusFilter, priorityFilter, offset],
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
    <div className="px-6 py-8 max-w-5xl mx-auto">
      <PageHeader
        title="My Tickets"
        description="View and manage all your support requests."
        actions={
          <Link to="/app/tickets/new">
            <Button
              id="ticket-list-create"
              size="sm"
              leftIcon={<PlusCircle className="w-4 h-4" />}
            >
              New Ticket
            </Button>
          </Link>
        }
      />

      {/* Filters */}
      <div className="flex items-center gap-3 mb-5 flex-wrap">
        <Select
          id="ticket-filter-status"
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value as TicketStatus | "");
            setOffset(0);
          }}
          options={STATUS_OPTIONS}
          className="w-44"
        />
        <Select
          id="ticket-filter-priority"
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
        <span className="ml-auto text-xs text-slate-400">{total} total</span>
      </div>

      {isError && (
        <Alert variant="error" className="mb-4">
          Failed to load tickets. Please refresh.
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
            description={
              statusFilter || priorityFilter
                ? "Try changing the filters above."
                : "You haven't created any tickets yet."
            }
            action={{
              label: "Create first ticket",
              onClick: () => window.location.replace("/app/tickets/new"),
            }}
          />
        ) : (
          <div className="divide-y divide-slate-100">
            {tickets.map((ticket: Ticket) => (
              <Link
                key={ticket.id}
                to={`/app/tickets/${ticket.id}`}
                className="flex items-center gap-4 px-6 py-4 hover:bg-slate-50 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-900 truncate">
                    {ticket.title}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    #{ticket.ticket_number} ·{" "}
                    {new Date(ticket.created_at).toLocaleDateString("en-US", {
                      year: "numeric",
                      month: "short",
                      day: "numeric",
                    })}
                    {ticket.category && ` · ${ticket.category}`}
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
