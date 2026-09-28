import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  Button,
  Badge,
  StatusBadge,
  PriorityBadge,
  ReviewStatusBadge,
  RoleBadge,
  Input,
  Textarea,
  Select,
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardFooter,
  Alert,
  EmptyState,
} from "@/components/ui";

describe("UI Components", () => {
  describe("Button", () => {
    it("renders children and handles click", () => {
      const handleClick = vi.fn();
      render(<Button onClick={handleClick}>Click Me</Button>);
      const btn = screen.getByRole("button", { name: /click me/i });
      expect(btn).toBeInTheDocument();
      fireEvent.click(btn);
      expect(handleClick).toHaveBeenCalledTimes(1);
    });

    it("displays loading spinner and disables button when isLoading is true", () => {
      render(<Button isLoading>Submit</Button>);
      const btn = screen.getByRole("button");
      expect(btn).toBeDisabled();
      expect(btn.querySelector("svg")).toBeInTheDocument();
    });

    it("renders left and right icons", () => {
      render(
        <Button
          leftIcon={<span data-testid="left-icon">L</span>}
          rightIcon={<span data-testid="right-icon">R</span>}
        >
          Icon Button
        </Button>
      );
      expect(screen.getByTestId("left-icon")).toBeInTheDocument();
      expect(screen.getByTestId("right-icon")).toBeInTheDocument();
    });
  });

  describe("Badges", () => {
    it("renders generic badge with variants", () => {
      const { rerender } = render(<Badge variant="brand">Brand</Badge>);
      expect(screen.getByText("Brand")).toBeInTheDocument();

      rerender(<Badge variant="danger">Danger</Badge>);
      expect(screen.getByText("Danger")).toBeInTheDocument();
    });

    it("renders StatusBadge accurately for various statuses", () => {
      const { rerender } = render(<StatusBadge status="OPEN" />);
      expect(screen.getByText("Open")).toBeInTheDocument();

      rerender(<StatusBadge status="PENDING_AGENT_REVIEW" />);
      expect(screen.getByText("Pending Review")).toBeInTheDocument();

      rerender(<StatusBadge status="RESOLVED" />);
      expect(screen.getByText("Resolved")).toBeInTheDocument();

      rerender(<StatusBadge status="CLOSED" />);
      expect(screen.getByText("Closed")).toBeInTheDocument();
    });

    it("renders PriorityBadge accurately", () => {
      const { rerender } = render(<PriorityBadge priority="URGENT" />);
      expect(screen.getByText("Urgent")).toBeInTheDocument();

      rerender(<PriorityBadge priority="HIGH" />);
      expect(screen.getByText("High")).toBeInTheDocument();

      rerender(<PriorityBadge priority="LOW" />);
      expect(screen.getByText("Low")).toBeInTheDocument();
    });

    it("renders ReviewStatusBadge accurately", () => {
      const { rerender } = render(<ReviewStatusBadge status="PENDING" />);
      expect(screen.getByText("Pending Triage")).toBeInTheDocument();

      rerender(<ReviewStatusBadge status="APPROVED" />);
      expect(screen.getByText("Approved")).toBeInTheDocument();

      rerender(<ReviewStatusBadge status="ESCALATED" />);
      expect(screen.getByText("Escalated Tier-2")).toBeInTheDocument();
    });

    it("renders RoleBadge accurately", () => {
      const { rerender } = render(<RoleBadge role="ADMIN" />);
      expect(screen.getByText("Admin")).toBeInTheDocument();

      rerender(<RoleBadge role="SUPPORT_AGENT" />);
      expect(screen.getByText("Support Agent")).toBeInTheDocument();

      rerender(<RoleBadge role="CUSTOMER" />);
      expect(screen.getByText("Customer")).toBeInTheDocument();
    });
  });

  describe("Input & Textarea & Select", () => {
    it("renders input with label and error", () => {
      render(
        <Input
          label="Email Address"
          placeholder="user@example.com"
          error="Invalid email"
        />
      );
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
      expect(screen.getByText("Invalid email")).toBeInTheDocument();
    });

    it("renders textarea with character count helper text", () => {
      render(
        <Textarea
          label="Description"
          helperText="42 characters"
          placeholder="Type here..."
        />
      );
      expect(screen.getByLabelText(/description/i)).toBeInTheDocument();
      expect(screen.getByText("42 characters")).toBeInTheDocument();
    });

    it("renders select with options and handles change", () => {
      const handleChange = vi.fn();
      render(
        <Select
          label="Category"
          options={[
            { value: "BILLING", label: "Billing" },
            { value: "TECHNICAL", label: "Technical" },
          ]}
          onChange={handleChange}
        />
      );
      const select = screen.getByLabelText(/category/i);
      expect(select).toBeInTheDocument();
      fireEvent.change(select, { target: { value: "TECHNICAL" } });
      expect(handleChange).toHaveBeenCalled();
    });
  });

  describe("Card & Alert & EmptyState", () => {
    it("renders card subcomponents", () => {
      render(
        <Card>
          <CardHeader>
            <CardTitle>Header Title</CardTitle>
          </CardHeader>
          <CardContent>Body content</CardContent>
          <CardFooter>Footer content</CardFooter>
        </Card>
      );
      expect(screen.getByText("Header Title")).toBeInTheDocument();
      expect(screen.getByText("Body content")).toBeInTheDocument();
      expect(screen.getByText("Footer content")).toBeInTheDocument();
    });

    it("renders alert with different variants", () => {
      render(
        <Alert variant="error" title="Error Title">
          Something failed.
        </Alert>
      );
      expect(screen.getByText("Error Title")).toBeInTheDocument();
      expect(screen.getByText("Something failed.")).toBeInTheDocument();
    });

    it("renders empty state", () => {
      render(
        <EmptyState
          title="No results found"
          description="Try adjusting your filters"
        />
      );
      expect(screen.getByText("No results found")).toBeInTheDocument();
      expect(screen.getByText("Try adjusting your filters")).toBeInTheDocument();
    });
  });
});
