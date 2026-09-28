/**
 * Create Ticket Page — /app/tickets/new
 */

import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ticketsApi } from "@/services/api";
import {
  Card,
  CardContent,
  Button,
  Input,
  Textarea,
  Select,
  Alert,
} from "@/components/ui";
import { PageHeader } from "@/components/layout/PageHeader";
import { useToast } from "@/components/ui/Toast";
import { CreateTicketRequest, TicketCategory, APIError } from "@/types";
import { ArrowLeft, Send } from "lucide-react";

const CATEGORY_OPTIONS: { value: TicketCategory; label: string }[] = [
  { value: "GENERAL", label: "General Inquiry" },
  { value: "BILLING", label: "Billing & Invoices" },
  { value: "ORDER_STATUS", label: "Order Status & Shipping" },
  { value: "TECHNICAL", label: "Technical Support" },
  { value: "RETURNS", label: "Returns & Exchanges" },
];

export const CreateTicketPage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<TicketCategory>("GENERAL");
  const [formError, setFormError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (data: CreateTicketRequest) => ticketsApi.createTicket(data),
    onSuccess: (ticket) => {
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      toast({
        title: "Ticket created",
        description: `#${ticket.ticket_number} submitted successfully.`,
        variant: "success",
      });
      navigate(`/app/tickets/${ticket.id}`);
    },
    onError: (err) => {
      const msg = err instanceof APIError ? err.message : "Failed to create ticket.";
      setFormError(msg);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!title.trim()) {
      setFormError("Title is required.");
      return;
    }
    if (description.trim().length < 10) {
      setFormError("Please provide a more detailed description (at least 10 characters).");
      return;
    }

    mutation.mutate({
      title: title.trim(),
      description: description.trim(),
      category,
    });
  };

  return (
    <div className="px-6 py-8 max-w-2xl mx-auto">
      <PageHeader
        title="Create Support Ticket"
        description="Describe your issue and our AI will assist you."
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

      <Card>
        <CardContent className="pt-6">
          {formError && (
            <Alert variant="error" className="mb-4">
              {formError}
            </Alert>
          )}
          <form onSubmit={handleSubmit} className="space-y-5" noValidate>
            <Input
              id="create-ticket-title"
              label="Title"
              placeholder="Brief summary of your issue"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              helperText="Keep it short and descriptive."
            />

            <Select
              id="create-ticket-category"
              label="Category"
              value={category}
              onChange={(e) => setCategory(e.target.value as TicketCategory)}
              options={CATEGORY_OPTIONS}
            />

            <Textarea
              id="create-ticket-description"
              label="Description"
              placeholder="Describe your issue in detail — what happened, what you expected, steps to reproduce…"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              required
              rows={6}
              helperText={`${description.length} characters`}
            />

            <div className="flex justify-end gap-3 pt-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate(-1)}
                disabled={mutation.isPending}
              >
                Cancel
              </Button>
              <Button
                id="create-ticket-submit"
                type="submit"
                isLoading={mutation.isPending}
                leftIcon={<Send className="w-4 h-4" />}
              >
                {mutation.isPending ? "Submitting…" : "Submit Ticket"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};
