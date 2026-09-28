/**
 * Agent Ticket Detail — /agent/tickets/:id
 * Full ticket view for agents with status management and message thread.
 */

import React, { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ticketsApi } from "@/services/api";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  StatusBadge,
  PriorityBadge,
  Badge,
  Button,
  Textarea,
  Select,
  Alert,
  Spinner,
} from "@/components/ui";
import { PageHeader } from "@/components/layout/PageHeader";
import { useToast } from "@/components/ui/Toast";
import { TicketStatus, TicketMessage, APIError } from "@/types";
import {
  ArrowLeft,
  MessageCircle,
  RefreshCw,
  Calendar,
  Tag,
  User,
  Send,
  Lock,
} from "lucide-react";

/**
 * Valid status transitions from each state.
 * Mirrors the VALID_STATUS_TRANSITIONS allowlist in backend/app/schemas/ticket.py.
 * Agents can only move to allowed next states; CLOSED is terminal.
 */
const STATUS_TRANSITIONS: Record<TicketStatus, TicketStatus[]> = {
  OPEN: ["AI_PROCESSING", "IN_PROGRESS", "CLOSED"],
  AI_PROCESSING: ["PENDING_CUSTOMER", "PENDING_AGENT_REVIEW", "RESOLVED", "OPEN"],
  PENDING_CUSTOMER: ["OPEN", "IN_PROGRESS", "CLOSED"],
  PENDING_AGENT_REVIEW: ["PENDING_CUSTOMER", "IN_PROGRESS", "RESOLVED", "CLOSED"],
  IN_PROGRESS: ["PENDING_CUSTOMER", "RESOLVED", "CLOSED"],
  RESOLVED: ["CLOSED", "OPEN"],
  CLOSED: [],
};

const STATUS_LABELS: Record<TicketStatus, string> = {
  OPEN: "Open",
  AI_PROCESSING: "AI Processing",
  PENDING_CUSTOMER: "Pending Customer",
  PENDING_AGENT_REVIEW: "Pending Agent Review",
  IN_PROGRESS: "In Progress",
  RESOLVED: "Resolved",
  CLOSED: "Closed",
};

export const AgentTicketDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [targetStatus, setTargetStatus] = useState<TicketStatus | "">("");
  const [internalNote, setInternalNote] = useState("");

  const {
    data: ticket,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["ticket", id],
    queryFn: () => ticketsApi.getTicket(id!),
    enabled: !!id,
  });

  // Status transition mutation — uses updateTicket (PATCH /tickets/{id})
  const statusMutation = useMutation({
    mutationFn: (status: TicketStatus) =>
      ticketsApi.updateTicket(id!, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ticket", id] });
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      toast({ title: "Status updated", variant: "success" });
      setTargetStatus("");
    },
    onError: (err) => {
      const msg = err instanceof APIError ? err.message : "Failed to update status";
      toast({ title: "Error", description: msg, variant: "error" });
    },
  });

  // Add internal note mutation
  const noteMutation = useMutation({
    mutationFn: (content: string) =>
      ticketsApi.addMessage(id!, { content, is_internal_note: true }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ticket", id] });
      toast({ title: "Internal note added", variant: "success" });
      setInternalNote("");
    },
    onError: (err) => {
      const msg = err instanceof APIError ? err.message : "Failed to add note";
      toast({ title: "Error", description: msg, variant: "error" });
    },
  });

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner size="lg" className="text-brand-600" />
      </div>
    );
  }

  if (isError || !ticket) {
    const msg = error instanceof APIError ? error.message : "Ticket not found.";
    return (
      <div className="px-6 py-8 max-w-4xl mx-auto">
        <Alert variant="error">{msg}</Alert>
        <Button
          variant="outline"
          size="sm"
          className="mt-4"
          onClick={() => navigate("/agent/tickets")}
          leftIcon={<ArrowLeft className="w-4 h-4" />}
        >
          Back to tickets
        </Button>
      </div>
    );
  }

  const currentStatus = ticket.status as TicketStatus;
  const transitions = STATUS_TRANSITIONS[currentStatus] || [];
  const statusOptions = [
    { value: "", label: "Update status…" },
    ...transitions.map((s) => ({ value: s, label: STATUS_LABELS[s] })),
  ];

  // Separate messages: customer messages and internal agent notes
  const messages = ticket.messages || [];
  const visibleMessages = messages.filter((m) => !m.is_internal_note);
  const internalNotes = messages.filter((m) => m.is_internal_note);

  return (
    <div className="px-6 py-8 max-w-4xl mx-auto">
      <PageHeader
        title={ticket.title}
        actions={
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(-1)}
            leftIcon={<ArrowLeft className="w-4 h-4" />}
          >
            Back
          </Button>
        }
      />

      {/* Meta row */}
      <div className="flex flex-wrap gap-2 mb-6">
        <StatusBadge status={currentStatus} size="md" />
        <PriorityBadge priority={ticket.priority} size="md" />
        {ticket.category && (
          <Badge variant="outline" className="flex items-center gap-1">
            <Tag className="w-3 h-3" />
            {ticket.category}
          </Badge>
        )}
        <Badge variant="outline" className="flex items-center gap-1 font-mono text-xs">
          #{ticket.ticket_number}
        </Badge>
        <Badge variant="outline" className="flex items-center gap-1 text-xs">
          <Calendar className="w-3 h-3" />
          {new Date(ticket.created_at).toLocaleDateString("en-US", {
            year: "numeric",
            month: "short",
            day: "numeric",
          })}
        </Badge>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left column: ticket content */}
        <div className="lg:col-span-2 space-y-4">
          {/* Description */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm">
                <MessageCircle className="w-4 h-4 text-slate-400" />
                Customer Request
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-slate-700 whitespace-pre-wrap">
                {ticket.description}
              </p>
            </CardContent>
          </Card>

          {/* Message thread */}
          {visibleMessages.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Message Thread</CardTitle>
              </CardHeader>
              <div className="divide-y divide-slate-100">
                {visibleMessages.map((msg: TicketMessage) => (
                  <div key={msg.id} className="px-5 py-3">
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={`text-xs font-semibold ${
                          msg.sender_type === "AI_SYSTEM"
                            ? "text-brand-600"
                            : msg.sender_type === "AGENT"
                            ? "text-emerald-600"
                            : "text-slate-600"
                        }`}
                      >
                        {msg.sender_type === "AI_SYSTEM"
                          ? "AI System"
                          : msg.sender_type === "AGENT"
                          ? "Support Agent"
                          : "Customer"}
                      </span>
                      <span className="text-xs text-slate-400">
                        {new Date(msg.created_at).toLocaleString("en-US", {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    </div>
                    <p className="text-sm text-slate-700 whitespace-pre-wrap">
                      {msg.content}
                    </p>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Internal notes */}
          {internalNotes.length > 0 && (
            <Card className="border-amber-100 bg-amber-50/30">
              <CardHeader>
                <CardTitle className="text-sm flex items-center gap-2 text-amber-700">
                  <Lock className="w-3.5 h-3.5" />
                  Internal Notes
                </CardTitle>
              </CardHeader>
              <div className="divide-y divide-amber-100">
                {internalNotes.map((note: TicketMessage) => (
                  <div key={note.id} className="px-5 py-3">
                    <p className="text-xs text-amber-600 mb-1">
                      {new Date(note.created_at).toLocaleString("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </p>
                    <p className="text-sm text-slate-700 whitespace-pre-wrap">
                      {note.content}
                    </p>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Add internal note */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Lock className="w-3.5 h-3.5 text-slate-400" />
                Add Internal Note
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Textarea
                id="agent-note-input"
                placeholder="Add an internal note (not visible to customer)…"
                rows={3}
                value={internalNote}
                onChange={(e) => setInternalNote(e.target.value)}
              />
              <div className="flex justify-end mt-3">
                <Button
                  id="agent-note-submit"
                  size="sm"
                  variant="outline"
                  onClick={() => noteMutation.mutate(internalNote)}
                  isLoading={noteMutation.isPending}
                  disabled={!internalNote.trim()}
                  leftIcon={<Send className="w-3.5 h-3.5" />}
                >
                  Add Note
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Right column: actions */}
        <div className="space-y-4">
          {/* Status transitions */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Update Status</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {transitions.length > 0 ? (
                <>
                  <Select
                    id="agent-status-select"
                    label="Transition To"
                    value={targetStatus}
                    onChange={(e) =>
                      setTargetStatus(e.target.value as TicketStatus)
                    }
                    options={statusOptions}
                  />
                  <Button
                    id="agent-status-update"
                    size="sm"
                    className="w-full"
                    onClick={() => {
                      if (targetStatus) statusMutation.mutate(targetStatus);
                    }}
                    isLoading={statusMutation.isPending}
                    disabled={!targetStatus}
                    leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
                  >
                    Apply Transition
                  </Button>
                </>
              ) : (
                <p className="text-sm text-slate-500 text-center py-2">
                  Ticket is closed — no further transitions.
                </p>
              )}
            </CardContent>
          </Card>

          {/* Resolution summary */}
          {(currentStatus === "RESOLVED" || currentStatus === "CLOSED") &&
            ticket.resolution_summary && (
              <Card className="border-emerald-100 bg-emerald-50/30">
                <CardHeader>
                  <CardTitle className="text-sm text-emerald-700">
                    Resolution Summary
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-slate-700 whitespace-pre-wrap">
                    {ticket.resolution_summary}
                  </p>
                </CardContent>
              </Card>
            )}

          {/* Ticket details */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-start gap-2">
                <User className="w-4 h-4 text-slate-400 mt-0.5 shrink-0" />
                <div>
                  <p className="text-xs text-slate-400">Customer ID</p>
                  <p className="text-slate-700 font-mono text-xs">
                    {ticket.customer_id}
                  </p>
                </div>
              </div>
              {ticket.assigned_agent_id && (
                <div>
                  <p className="text-xs text-slate-400">Assigned Agent</p>
                  <p className="text-slate-700 font-mono text-xs">
                    {ticket.assigned_agent_id}
                  </p>
                </div>
              )}
              {ticket.closed_at && (
                <div>
                  <p className="text-xs text-slate-400">Closed At</p>
                  <p className="text-slate-700 text-xs">
                    {new Date(ticket.closed_at).toLocaleString("en-US", {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
};
