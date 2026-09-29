import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ToastProvider } from "@/components/ui/Toast";
import { CreateTicketPage } from "@/pages/customer/CreateTicketPage";
import { CustomerTicketListPage } from "@/pages/customer/CustomerTicketListPage";
import { CustomerTicketDetailPage } from "@/pages/customer/CustomerTicketDetailPage";
import { AnalyticsDashboardPage } from "@/pages/admin/AnalyticsDashboardPage";
import { ReviewQueuePage } from "@/pages/agent/ReviewQueuePage";
import { KnowledgeBasePage } from "@/pages/agent/KnowledgeBasePage";
import { ticketsApi, analyticsApi, reviewsApi, knowledgeApi } from "@/services/api";
import { APIError } from "@/types";

const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

const renderWithProviders = (
  ui: React.ReactElement,
  client: QueryClient,
  route = "/"
) => {
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
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

    it("displays error alert when ticket creation API fails", async () => {
      vi.spyOn(ticketsApi, "createTicket").mockRejectedValue(
        new APIError("Server rejected ticket creation.", 500)
      );

      renderWithProviders(<CreateTicketPage />, queryClient);

      fireEvent.change(screen.getByLabelText(/title/i), {
        target: { value: "Valid Title" },
      });
      fireEvent.change(screen.getByLabelText(/description/i), {
        target: { value: "Valid detailed description of the problem." },
      });

      fireEvent.click(screen.getByRole("button", { name: "Submit Ticket" }));

      expect(
        await screen.findByText("Server rejected ticket creation.")
      ).toBeInTheDocument();
    });
  });

  describe("CustomerTicketListPage", () => {
    it("renders empty state when customer has no tickets", async () => {
      vi.spyOn(ticketsApi, "listTickets").mockResolvedValue({
        tickets: [],
        total: 0,
        offset: 0,
        limit: 15,
      });

      renderWithProviders(<CustomerTicketListPage />, queryClient);

      expect(screen.getByText("My Tickets")).toBeInTheDocument();
      expect(await screen.findByText("No tickets found")).toBeInTheDocument();
      expect(
        screen.getByText("You haven't created any tickets yet.")
      ).toBeInTheDocument();
    });

    it("displays error alert when ticket list API fails", async () => {
      vi.spyOn(ticketsApi, "listTickets").mockRejectedValue(
        new APIError("Failed to fetch tickets.", 500)
      );

      renderWithProviders(<CustomerTicketListPage />, queryClient);

      expect(
        await screen.findByText("Failed to load tickets. Please refresh.")
      ).toBeInTheDocument();
    });
  });

  describe("CustomerTicketDetailPage", () => {
    it("renders ticket detail and messages for a valid ticket", async () => {
      vi.spyOn(ticketsApi, "getTicket").mockResolvedValue({
        id: "t-1",
        ticket_number: "TKT-2026-001",
        customer_id: "c-1",
        title: "Cannot reset password",
        description: "Password reset link is broken.",
        category: "TECHNICAL",
        priority: "MEDIUM",
        status: "OPEN",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        messages: [
          {
            id: "m-1",
            ticket_id: "t-1",
            sender_type: "CUSTOMER",
            content: "Please help me reset my password.",
            is_internal_note: false,
            created_at: new Date().toISOString(),
          },
        ],
      });

      render(
        <QueryClientProvider client={queryClient}>
          <ToastProvider>
            <MemoryRouter initialEntries={["/app/tickets/t-1"]}>
              <Routes>
                <Route
                  path="/app/tickets/:id"
                  element={<CustomerTicketDetailPage />}
                />
              </Routes>
            </MemoryRouter>
          </ToastProvider>
        </QueryClientProvider>
      );

      expect(await screen.findByText("Cannot reset password")).toBeInTheDocument();
      expect(screen.getByText("#TKT-2026-001")).toBeInTheDocument();
      expect(
        screen.getByText("Please help me reset my password.")
      ).toBeInTheDocument();
    });

    it("renders error state when ticket is not found", async () => {
      vi.spyOn(ticketsApi, "getTicket").mockRejectedValue(
        new APIError("Ticket not found.", 404)
      );

      render(
        <QueryClientProvider client={queryClient}>
          <ToastProvider>
            <MemoryRouter initialEntries={["/app/tickets/nonexistent"]}>
              <Routes>
                <Route
                  path="/app/tickets/:id"
                  element={<CustomerTicketDetailPage />}
                />
              </Routes>
            </MemoryRouter>
          </ToastProvider>
        </QueryClientProvider>
      );

      expect(await screen.findByText("Ticket not found.")).toBeInTheDocument();
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

    it("correctly renders zero-value metrics without omitting them", async () => {
      vi.spyOn(analyticsApi, "getSummary").mockResolvedValue({
        total_tickets: 0,
        open_tickets: 0,
        resolved_tickets: 0,
        in_progress_tickets: 0,
        pending_review_tickets: 0,
        closed_tickets: 0,
        total_reviews: 0,
        pending_reviews: 0,
        completed_reviews: 0,
        total_ai_runs: 0,
        average_confidence: null,
        tickets_by_status: {},
        tickets_by_category: {},
        tickets_by_priority: {},
        reviews_by_status: {},
      });

      renderWithProviders(<AnalyticsDashboardPage />, queryClient);

      expect(screen.getByText("Analytics Dashboard")).toBeInTheDocument();
      const zeroes = await screen.findAllByText("0");
      expect(zeroes.length).toBeGreaterThanOrEqual(4);
    });

    it("displays error alert when analytics API fails", async () => {
      vi.spyOn(analyticsApi, "getSummary").mockRejectedValue(
        new APIError("Analytics unavailable.", 500)
      );

      renderWithProviders(<AnalyticsDashboardPage />, queryClient);

      expect(
        await screen.findByText("Failed to load analytics. Please refresh.")
      ).toBeInTheDocument();
    });
  });

  describe("ReviewQueuePage", () => {
    const mockReviewItem = {
      id: "rev-1",
      ticket_id: "tick-1",
      ai_run_id: "run-1",
      status: "PENDING" as const,
      escalation_reason: "High refund amount ($250)",
      original_ai_draft: "We have processed your refund of $250.",
      ticket_title: "Refund inquiry",
      ticket_number: "TICK-001",
      ticket_priority: "HIGH",
      ticket_category: "BILLING",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    it("renders reviews queue items and actions", async () => {
      vi.spyOn(reviewsApi, "listReviews").mockResolvedValue({
        total: 1,
        items: [mockReviewItem],
      });

      renderWithProviders(<ReviewQueuePage />, queryClient);

      expect(screen.getByText("Review Queue")).toBeInTheDocument();
      expect(await screen.findByText(/High refund amount/i)).toBeInTheDocument();
      expect(
        screen.getByText(/We have processed your refund of \$250/i)
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /edit response/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /reject/i })).toBeInTheDocument();
    });

    it("renders empty state when queue is clear", async () => {
      vi.spyOn(reviewsApi, "listReviews").mockResolvedValue({
        total: 0,
        items: [],
      });

      renderWithProviders(<ReviewQueuePage />, queryClient);

      expect(await screen.findByText("Queue is clear!")).toBeInTheDocument();
      expect(
        screen.getByText(/All AI responses are within confidence thresholds/i)
      ).toBeInTheDocument();
    });

    it("executes approve action successfully", async () => {
      vi.spyOn(reviewsApi, "listReviews").mockResolvedValue({
        total: 1,
        items: [mockReviewItem],
      });
      const approveSpy = vi.spyOn(reviewsApi, "approveReview").mockResolvedValue({
        ...mockReviewItem,
        status: "APPROVED",
      });

      renderWithProviders(<ReviewQueuePage />, queryClient);

      const approveBtn = await screen.findByRole("button", { name: /approve/i });
      fireEvent.click(approveBtn);

      await waitFor(() => {
        expect(approveSpy).toHaveBeenCalledWith("rev-1", { notes: undefined });
      });
    });

    it("executes edit response and diff preview flow", async () => {
      vi.spyOn(reviewsApi, "listReviews").mockResolvedValue({
        total: 1,
        items: [mockReviewItem],
      });
      const editSpy = vi.spyOn(reviewsApi, "editReview").mockResolvedValue({
        ...mockReviewItem,
        status: "EDITED",
        final_submitted_text: "We have credited $250 back to your account.",
      });

      renderWithProviders(<ReviewQueuePage />, queryClient);

      // Enter edit mode
      const editBtn = await screen.findByRole("button", { name: /edit response/i });
      fireEvent.click(editBtn);

      // Verify diff preview tab switch
      const diffTab = screen.getByRole("button", { name: "Diff Preview" });
      fireEvent.click(diffTab);
      expect(screen.getByText("Original AI Draft")).toBeInTheDocument();
      expect(screen.getByText("Human-Edited Text")).toBeInTheDocument();

      // Switch back to edit and modify text
      const editTab = screen.getByRole("button", { name: "Edit Response" });
      fireEvent.click(editTab);

      const textArea = screen.getByLabelText(/response to send to customer/i);
      fireEvent.change(textArea, {
        target: { value: "We have credited $250 back to your account." },
      });

      const submitEditBtn = screen.getByRole("button", {
        name: /submit edited response/i,
      });
      fireEvent.click(submitEditBtn);

      await waitFor(() => {
        expect(editSpy).toHaveBeenCalledWith("rev-1", {
          final_submitted_text: "We have credited $250 back to your account.",
          notes: undefined,
        });
      });
    });

    it("executes reject action successfully", async () => {
      vi.spyOn(reviewsApi, "listReviews").mockResolvedValue({
        total: 1,
        items: [mockReviewItem],
      });
      const rejectSpy = vi.spyOn(reviewsApi, "rejectReview").mockResolvedValue({
        ...mockReviewItem,
        status: "REJECTED",
      });

      renderWithProviders(<ReviewQueuePage />, queryClient);

      const rejectBtn = await screen.findByRole("button", { name: /reject/i });
      fireEvent.click(rejectBtn);

      await waitFor(() => {
        expect(rejectSpy).toHaveBeenCalledWith("rev-1", {
          feedback_notes: "Rejected by reviewer",
        });
      });
    });

    it("displays error alert when review queue API fails", async () => {
      vi.spyOn(reviewsApi, "listReviews").mockRejectedValue(
        new APIError("Queue offline.", 503)
      );

      renderWithProviders(<ReviewQueuePage />, queryClient);

      expect(
        await screen.findByText(
          "Failed to load the review queue. Please try refreshing."
        )
      ).toBeInTheDocument();
    });
  });

  describe("KnowledgeBasePage", () => {
    it("renders document list when available", async () => {
      vi.spyOn(knowledgeApi, "listDocuments").mockResolvedValue({
        documents: [
          {
            id: "doc-1",
            title: "Refund and Return Policy",
            source_type: "MARKDOWN",
            checksum_sha256: "abc123",
            is_active: true,
            chunk_count: 5,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        total: 1,
        offset: 0,
        limit: 30,
      });

      renderWithProviders(<KnowledgeBasePage />, queryClient);

      expect(screen.getByText("Knowledge Base")).toBeInTheDocument();
      expect(
        await screen.findByText("Refund and Return Policy")
      ).toBeInTheDocument();
      expect(screen.getByText(/5 chunks/i)).toBeInTheDocument();
    });

    it("renders empty state when no documents are ingested", async () => {
      vi.spyOn(knowledgeApi, "listDocuments").mockResolvedValue({
        documents: [],
        total: 0,
        offset: 0,
        limit: 30,
      });

      renderWithProviders(<KnowledgeBasePage />, queryClient);

      expect(
        await screen.findByText("No documents ingested")
      ).toBeInTheDocument();
    });

    it("displays error alert when knowledge documents API fails", async () => {
      vi.spyOn(knowledgeApi, "listDocuments").mockRejectedValue(
        new APIError("Failed to fetch documents.", 500)
      );

      renderWithProviders(<KnowledgeBasePage />, queryClient);

      expect(
        await screen.findByText("Failed to load knowledge documents.")
      ).toBeInTheDocument();
    });
  });
});
