import React from "react";
import { cn } from "@/utils/cn";
import { TicketPriority, TicketStatus, ReviewStatus, UserRole } from "@/types";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?:
    | "default"
    | "success"
    | "warning"
    | "danger"
    | "info"
    | "neutral"
    | "brand"
    | "secondary"
    | "outline"
    | "error";
  size?: "sm" | "md";
}

export const Badge: React.FC<BadgeProps> = ({
  className,
  variant = "default",
  size = "md",
  children,
  ...props
}) => {
  const variantStyles = {
    default: "bg-slate-100 text-slate-700 border-slate-200",
    secondary: "bg-slate-100 text-slate-600 border-slate-200",
    neutral: "bg-gray-100 text-gray-700 border-gray-200",
    brand: "bg-brand-50 text-brand-700 border-brand-200",
    info: "bg-sky-50 text-sky-700 border-sky-200",
    success: "bg-emerald-50 text-emerald-700 border-emerald-200",
    warning: "bg-amber-50 text-amber-700 border-amber-200",
    danger: "bg-rose-50 text-rose-700 border-rose-200",
    error: "bg-rose-50 text-rose-700 border-rose-200",
    outline: "bg-transparent text-slate-700 border-slate-300",
  };

  const sizeStyles = {
    sm: "px-2 py-0.5 text-xs font-medium",
    md: "px-2.5 py-1 text-xs font-semibold",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border tracking-wide",
        variantStyles[variant],
        sizeStyles[size],
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
};

// Convenience status badges
export const StatusBadge: React.FC<{
  status: TicketStatus | string;
  size?: "sm" | "md";
  className?: string;
}> = ({ status, size, className }) => {
  switch (status) {
    case "OPEN":
      return <Badge variant="info" size={size} className={className}>Open</Badge>;
    case "AI_PROCESSING":
      return <Badge variant="brand" size={size} className={className}>AI Processing</Badge>;
    case "PENDING_CUSTOMER":
      return <Badge variant="warning" size={size} className={className}>Waiting on Customer</Badge>;
    case "PENDING_AGENT_REVIEW":
      return <Badge variant="danger" size={size} className={className}>Pending Review</Badge>;
    case "IN_PROGRESS":
      return <Badge variant="brand" size={size} className={className}>In Progress</Badge>;
    case "RESOLVED":
      return <Badge variant="success" size={size} className={className}>Resolved</Badge>;
    case "CLOSED":
      return <Badge variant="neutral" size={size} className={className}>Closed</Badge>;
    default:
      return <Badge variant="default" size={size} className={className}>{status}</Badge>;
  }
};

export const PriorityBadge: React.FC<{
  priority: TicketPriority | string;
  size?: "sm" | "md";
  className?: string;
}> = ({ priority, size, className }) => {
  switch (priority) {
    case "URGENT":
      return <Badge variant="danger" size={size} className={className}>Urgent</Badge>;
    case "HIGH":
      return <Badge variant="warning" size={size} className={className}>High</Badge>;
    case "MEDIUM":
      return <Badge variant="info" size={size} className={className}>Medium</Badge>;
    case "LOW":
      return <Badge variant="neutral" size={size} className={className}>Low</Badge>;
    default:
      return <Badge variant="default" size={size} className={className}>{priority}</Badge>;
  }
};

export const ReviewStatusBadge: React.FC<{
  status: ReviewStatus | string;
  size?: "sm" | "md";
  className?: string;
}> = ({ status, size, className }) => {
  switch (status) {
    case "PENDING":
      return <Badge variant="warning" size={size} className={className}>Pending Triage</Badge>;
    case "APPROVED":
      return <Badge variant="success" size={size} className={className}>Approved</Badge>;
    case "EDITED":
      return <Badge variant="info" size={size} className={className}>Edited & Sent</Badge>;
    case "REJECTED":
      return <Badge variant="danger" size={size} className={className}>Rejected</Badge>;
    case "ESCALATED":
      return <Badge variant="brand" size={size} className={className}>Escalated Tier-2</Badge>;
    default:
      return <Badge variant="default" size={size} className={className}>{status}</Badge>;
  }
};

export const RoleBadge: React.FC<{
  role: UserRole | string;
  size?: "sm" | "md";
  className?: string;
}> = ({ role, size, className }) => {
  switch (role) {
    case "ADMIN":
      return <Badge variant="danger" size={size} className={className}>Admin</Badge>;
    case "SUPPORT_AGENT":
      return <Badge variant="brand" size={size} className={className}>Support Agent</Badge>;
    case "CUSTOMER":
      return <Badge variant="success" size={size} className={className}>Customer</Badge>;
    default:
      return <Badge variant="default" size={size} className={className}>{role}</Badge>;
  }
};
