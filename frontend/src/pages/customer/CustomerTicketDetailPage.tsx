/**
 * Customer Ticket Detail — /app/tickets/:id
 * Shows full ticket details including conversation thread.
 * Customers can close their RESOLVED tickets from here.
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
  Alert,
  Spinner,
} from "@/components/ui";
import { PageHeader } from "@/components/layout/PageHeader";
import { useToast } from "@/components/ui/Toast";
import { TicketMessage, APIError } from "@/types";
import {
  ArrowLeft,
  Bot,
  MessageCircle,
  CheckCircle2,
  Calendar,
  Tag,
  Send,
} from "lucide-react";

export const CustomerTicketDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [replyText, setReplyText] = useState("");

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

  // Close ticket — uses updateTicket (PATCH /tickets/{id}) with status: "CLOSED"
  const closeMutation = useMutation({
    mutationFn: () =>
      ticketsApi.updateTicket(id!, { status: "CLOSED" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ticket", id] });
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      toast({ title: "Ticket closed", variant: "success" });
    },
    onError: (err) => {
      const msg = err instanceof APIError ? err.message : "Failed to close ticket";
      toast({ title: "Error", description: msg, variant: "error" });
    },
  });

  // Add customer reply
  const replyMutation = useMutation({
    mutationFn: (content: string) =>
      ticketsApi.addMessage(id!, { content, is_internal_note: false }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ticket", id] });
      toast({ title: "Reply sent", variant: "success" });
      setReplyText("");
    },
    onError: (err) => {
      const msg = err instanceof APIError ? err.message : "Failed to send reply";
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
      <div className="px-6 py-8 max-w-3xl mx-auto">
        <Alert variant="error">{msg}</Alert>
        <Button
          variant="outline"
          size="sm"
          className="mt-4"
          onClick={() => navigate("/app/tickets")}
          leftIcon={<ArrowLeft className="w-4 h-4" />}
        >
          Back to tickets
        </Button>
      </div>
    );
  }

  // Customers can close RESOLVED tickets (re-open via backend only)
  const canClose = ticket.status === "RESOLVED";
  const isClosed = ticket.status === "CLOSED";

  // Filter out internal notes (backend already does this, but be defensive)
  const messages = (ticket.messages || []).filter((m) => !m.is_internal_note);
  const aiMessages = messages.filter((m) => m.sender_type === "AI_SYSTEM");
  const threadMessages = messages;

  return (
    <div className="px-6 py-8 max-w-3xl mx-auto">
      <PageHeader
        title={ticket.title}
        actions={
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate("/app/tickets")}
            leftIcon={<ArrowLeft className="w-4 h-4" />}
          >
            Back
          </Button>
        }
      />

      {/* Meta */}
      <div className="flex flex-wrap gap-2 mb-6">
        <StatusBadge status={ticket.status} size="md" />
        <PriorityBadge priority={ticket.priority} size="md" />
        {ticket.category && (
          <Badge variant="outline" className="flex items-center gap-1">
            <Tag className="w-3 h-3" />
            {ticket.category}
          </Badge>
        )}
        <Badge variant="outline" className="flex items-center gap-1">
          <Calendar className="w-3 h-3" />
          {new Date(ticket.created_at).toLocaleDateString("en-US", {
            year: "numeric",
            month: "long",
            day: "numeric",
          })}
        </Badge>
        <Badge variant="secondary" className="font-mono text-xs">
          #{ticket.ticket_number}
        </Badge>
      </div>

      {/* Original description */}
      <Card className="mb-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <MessageCircle className="w-4 h-4 text-slate-400" />
            Your request
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-slate-700 whitespace-pre-wrap">
            {ticket.description}
          </p>
        </CardContent>
      </Card>

      {/* AI Responses from message thread */}
      {aiMessages.length > 0 && (
        <Card className="mb-4 border-brand-100 bg-brand-50/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm text-brand-700">
              <Bot className="w-4 h-4" />
              AI Response
              <Badge variant="brand" size="sm">SupportFlow AI</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {aiMessages.map((msg: TicketMessage) => (
              <p key={msg.id} className="text-sm text-slate-700 whitespace-pre-wrap">
                {msg.content}
              </p>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Full conversation thread (non-AI messages) */}
      {threadMessages.filter((m) => m.sender_type !== "AI_SYSTEM").length > 0 && (
        <Card className="mb-4">
          <CardHeader>
            <CardTitle className="text-sm">Conversation</CardTitle>
          </CardHeader>
          <div className="divide-y divide-slate-100">
            {threadMessages
              .filter((m) => m.sender_type !== "AI_SYSTEM")
              .map((msg: TicketMessage) => (
                <div key={msg.id} className="px-5 py-3">
                  <p className="text-xs font-semibold text-slate-500 mb-1">
                    {msg.sender_type === "AGENT" ? "Support Agent" : "You"} ·{" "}
                    {new Date(msg.created_at).toLocaleString("en-US", {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </p>
                  <p className="text-sm text-slate-700 whitespace-pre-wrap">
                    {msg.content}
                  </p>
                </div>
              ))}
          </div>
        </Card>
      )}

      {/* Resolution summary */}
      {ticket.resolution_summary && (
        <Card className="mb-4 border-emerald-100 bg-emerald-50/30">
          <CardHeader>
            <CardTitle className="text-sm text-emerald-700">
              Resolution
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-slate-700 whitespace-pre-wrap">
              {ticket.resolution_summary}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Reply box — only for open/in-progress tickets */}
      {!isClosed && (
        <Card className="mb-4">
          <CardHeader>
            <CardTitle className="text-sm">Send a Reply</CardTitle>
          </CardHeader>
          <CardContent>
            <Textarea
              id="customer-reply-input"
              placeholder="Add more details or respond to the agent…"
              rows={3}
              value={replyText}
              onChange={(e) => setReplyText(e.target.value)}
            />
            <div className="flex justify-end mt-3">
              <Button
                id="customer-reply-submit"
                size="sm"
                onClick={() => replyMutation.mutate(replyText)}
                isLoading={replyMutation.isPending}
                disabled={!replyText.trim()}
                leftIcon={<Send className="w-3.5 h-3.5" />}
              >
                Send Reply
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Close ticket action */}
      {canClose && (
        <div className="flex justify-end">
          <Button
            id="ticket-close-btn"
            variant="outline"
            size="sm"
            onClick={() => closeMutation.mutate()}
            isLoading={closeMutation.isPending}
            leftIcon={<CheckCircle2 className="w-4 h-4" />}
          >
            Mark as Closed
          </Button>
        </div>
      )}
    </div>
  );
};
