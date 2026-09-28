import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ToastProvider } from "@/components/ui/Toast";
import { CreateTicketPage } from "@/pages/customer/CreateTicketPage";
import { AnalyticsDashboardPage } from "@/pages/admin/AnalyticsDashboardPage";
import { ReviewQueuePage } from "@/pages/agent/ReviewQueuePage";
import { ticketsApi, analyticsApi, reviewsApi } from "@/services/api";

const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

const renderWithProviders = (ui: React.ReactElement, client: QueryClient) => {
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
};

describe("Page Components", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createQueryClient();
    vi.clearAllMocks();
  });

  describe("CreateTicketPage", () => {
    it("renders ticket creation form fields", () => {
      renderWithProviders(<CreateTicketPage />, queryClient);

      expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/category/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/description/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /submit ticket/i })).toBeInTheDocument();
    });

    it("validates empty title and short description before submitting", async () => {
      renderWithProviders(<CreateTicketPage />, queryClient);

      const submitBtn = screen.getByRole("button", { name: /submit ticket/i });
      fireEvent.click(submitBtn);

      expect(await screen.findByText("Title is required.")).toBeInTheDocument();

      const titleInput = screen.getByLabelText(/title/i);
      fireEvent.change(titleInput, { target: { value: "Test Title" } });
      fireEvent.click(submitBtn);

      expect(
        await screen.findByText(/please provide a more detailed description/i)
      ).toBeInTheDocument();
    });

    it("submits valid ticket data", async () => {
      const createSpy = vi.spyOn(ticketsApi, "createTicket").mockResolvedValue({
        id: "t-101",
        ticket_number: "TICK-101",
        customer_id: "c-1",
        title: "Refund Request",
        description: "I would like a refund for order #999.",
        category: "BILLING",
        priority: "MEDIUM",
        status: "OPEN",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });

      renderWithProviders(<CreateTicketPage />, queryClient);

      fireEvent.change(screen.getByLabelText(/title/i), {
        target: { value: "Refund Request" },
      });
      fireEvent.change(screen.getByLabelText(/description/i), {
        target: { value: "I would like a refund for order #999." },
      });
      fireEvent.change(screen.getByLabelText(/category/i), {
        target: { value: "BILLING" },
      });

      fireEvent.click(screen.getByRole("button", { name: "Submit Ticket" }));

      await waitFor(() => {
        expect(createSpy).toHaveBeenCalledWith({
          title: "Refund Request",
          description: "I would like a refund for order #999.",
          category: "BILLING",
        });
      });
    });
  });

  describe("AnalyticsDashboardPage", () => {
    it("renders operational metric cards and charts", async () => {
      vi.spyOn(analyticsApi, "getSummary").mockResolvedValue({
        total_tickets: 150,
        open_tickets: 25,
        resolved_tickets: 110,
        in_progress_tickets: 10,
        pending_review_tickets: 5,
        closed_tickets: 0,
        total_reviews: 40,
        pending_reviews: 3,
        completed_reviews: 37,
        total_ai_runs: 120,
        average_confidence: 0.88,
        tickets_by_status: { OPEN: 25, RESOLVED: 110 },
        tickets_by_category: { BILLING: 60, TECHNICAL: 90 },
        tickets_by_priority: { HIGH: 30, MEDIUM: 120 },
        reviews_by_status: { APPROVED: 30, EDITED: 7 },
      });

      renderWithProviders(<AnalyticsDashboardPage />, queryClient);

      expect(screen.getByText("Analytics Dashboard")).toBeInTheDocument();
      expect(await screen.findByText("150")).toBeInTheDocument();
      expect(await screen.findByText("88%")).toBeInTheDocument();
      expect(screen.getByText("Total Tickets")).toBeInTheDocument();
      expect(screen.getByText("Total AI Runs")).toBeInTheDocument();
    });
  });

  describe("ReviewQueuePage", () => {
    it("renders reviews queue items and actions", async () => {
      vi.spyOn(reviewsApi, "listReviews").mockResolvedValue({
        total: 1,
        items: [
          {
            id: "rev-1",
            ticket_id: "tick-1",
            ai_run_id: "run-1",
            status: "PENDING",
            escalation_reason: "High refund amount ($250)",
            original_ai_draft: "We have processed your refund of $250.",
            ticket_title: "Refund inquiry",
            ticket_number: "TICK-001",
            ticket_priority: "HIGH",
            ticket_category: "BILLING",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
      });

      renderWithProviders(<ReviewQueuePage />, queryClient);

      expect(screen.getByText("Review Queue")).toBeInTheDocument();
      expect(await screen.findByText(/High refund amount/i)).toBeInTheDocument();
      expect(screen.getByText(/We have processed your refund of \$250/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    });
  });
});
