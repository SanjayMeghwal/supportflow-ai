/**
 * Agent Review Queue — /agent/reviews
 * Human-in-the-loop review queue for AI-flagged tickets.
 * Agents can approve, edit, reject, or escalate each pending review.
 */

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { reviewsApi } from "@/services/api";
import {
  Card,
  CardHeader,
  CardContent,
  Badge,
  ReviewStatusBadge,
  Button,
  Textarea,
  Alert,
  EmptyState,
  Skeleton,
  Pagination,
} from "@/components/ui";
import { PageHeader } from "@/components/layout/PageHeader";
import { useToast } from "@/components/ui/Toast";
import { ReviewItem, APIError } from "@/types";
import {
  ClipboardList,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronUp,
  Edit3,
} from "lucide-react";

const PAGE_SIZE = 10;

/** Per-review card: shows AI draft, accept/edit/reject actions for PENDING items. */
const ReviewCard: React.FC<{
  review: ReviewItem;
  onApprove: (id: string, notes: string) => void;
  onReject: (id: string, notes: string) => void;
  isActioning: boolean;
}> = ({ review, onApprove, onReject, isActioning }) => {
  const [expanded, setExpanded] = useState(false);
  const [notes, setNotes] = useState("");

  const isPending = review.status === "PENDING";
  const aiDraft = review.original_ai_draft;

  return (
    <Card className="overflow-hidden animate-in">
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              {review.ticket_number && (
                <span className="text-xs font-mono text-slate-400">
                  #{review.ticket_number}
                </span>
              )}
              {review.ticket_title && (
                <p className="text-sm font-semibold text-slate-900 truncate">
                  {review.ticket_title}
                </p>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Escalation: {review.escalation_reason}
              {review.ticket_priority && (
                <> · Priority: <span className="capitalize">{review.ticket_priority.toLowerCase()}</span></>
              )}
            </p>
          </div>
          <ReviewStatusBadge status={review.status} />
        </div>
      </CardHeader>

      {aiDraft && (
        <CardContent>
          {/* AI draft */}
          <div className="mb-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
              AI Draft Response
            </p>
            <div
              className={`text-sm text-slate-700 whitespace-pre-wrap overflow-hidden transition-all ${
                expanded ? "max-h-none" : "max-h-24"
              }`}
            >
              {aiDraft}
            </div>
            {aiDraft.length > 200 && (
              <button
                className="mt-2 text-xs text-brand-600 hover:text-brand-700 font-medium flex items-center gap-1"
                onClick={() => setExpanded(!expanded)}
              >
                {expanded ? (
                  <><ChevronUp className="w-3 h-3" /> Show less</>
                ) : (
                  <><ChevronDown className="w-3 h-3" /> Show more</>
                )}
              </button>
            )}
          </div>

          {/* Action area — only for PENDING reviews */}
          {isPending && (
            <div className="mt-4 pt-4 border-t border-slate-100 space-y-3">
              <Textarea
                id={`review-notes-${review.id}`}
                label="Review Notes (optional)"
                placeholder="Add context for your decision…"
                rows={2}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
              <div className="flex gap-2 justify-end">
                <Button
                  id={`review-reject-${review.id}`}
                  size="sm"
                  variant="outline"
                  className="text-rose-600 border-rose-200 hover:bg-rose-50"
                  onClick={() => onReject(review.id, notes)}
                  isLoading={isActioning}
                  leftIcon={<XCircle className="w-3.5 h-3.5" />}
                >
                  Reject
                </Button>
                <Button
                  id={`review-approve-${review.id}`}
                  size="sm"
                  className="bg-emerald-600 hover:bg-emerald-700 text-white"
                  onClick={() => onApprove(review.id, notes)}
                  isLoading={isActioning}
                  leftIcon={<CheckCircle2 className="w-3.5 h-3.5" />}
                >
                  Approve
                </Button>
              </div>
            </div>
          )}

          {/* Reviewer notes for completed reviews */}
          {!isPending && review.feedback_notes && (
            <div className="mt-3 pt-3 border-t border-slate-100">
              <p className="text-xs text-slate-500 font-medium">Reviewer Notes</p>
              <p className="text-sm text-slate-700 mt-1">{review.feedback_notes}</p>
            </div>
          )}

          {!isPending && review.final_submitted_text && (
            <div className="mt-3 pt-3 border-t border-slate-100">
              <p className="text-xs text-slate-500 font-medium flex items-center gap-1">
                <Edit3 className="w-3 h-3" /> Final Submitted Text
              </p>
              <p className="text-sm text-slate-700 mt-1 whitespace-pre-wrap">
                {review.final_submitted_text}
              </p>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
};

export const ReviewQueuePage: React.FC = () => {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [offset, setOffset] = useState(0);
  const [actioningId, setActioningId] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["reviews", "pending", offset],
    queryFn: () =>
      reviewsApi.listReviews({
        skip: offset,
        limit: PAGE_SIZE,
      }),
    staleTime: 15_000,
  });

  const approveMutation = useMutation({
    mutationFn: ({ id, notes }: { id: string; notes: string }) =>
      reviewsApi.approveReview(id, { notes: notes || undefined }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
      toast({ title: "Review approved", variant: "success" });
      setActioningId(null);
    },
    onError: (err) => {
      const msg = err instanceof APIError ? err.message : "Approval failed";
      toast({ title: "Error", description: msg, variant: "error" });
      setActioningId(null);
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({ id, notes }: { id: string; notes: string }) =>
      reviewsApi.rejectReview(id, { feedback_notes: notes || "Rejected by reviewer" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
      toast({ title: "Review rejected", variant: "success" });
      setActioningId(null);
    },
    onError: (err) => {
      const msg = err instanceof APIError ? err.message : "Rejection failed";
      toast({ title: "Error", description: msg, variant: "error" });
      setActioningId(null);
    },
  });

  const handleApprove = (id: string, notes: string) => {
    setActioningId(id);
    approveMutation.mutate({ id, notes });
  };

  const handleReject = (id: string, notes: string) => {
    setActioningId(id);
    rejectMutation.mutate({ id, notes });
  };

  const reviews = data?.items || [];
  const total = data?.total || 0;

  return (
    <div className="px-6 py-8 max-w-3xl mx-auto">
      <PageHeader
        title="Review Queue"
        description="AI-flagged responses requiring human review before delivery."
        actions={
          total > 0 ? (
            <Badge variant="error">{total} pending</Badge>
          ) : undefined
        }
      />

      {isError && (
        <Alert variant="error" className="mb-4">
          Failed to load the review queue. Please try refreshing.
        </Alert>
      )}

      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="p-6">
              <Skeleton className="h-5 w-1/3 mb-3" />
              <Skeleton className="h-4 w-full mb-2" />
              <Skeleton className="h-4 w-3/4" />
            </Card>
          ))}
        </div>
      ) : reviews.length === 0 ? (
        <EmptyState
          icon={<ClipboardList className="w-7 h-7" />}
          title="Queue is clear!"
          description="All AI responses are within confidence thresholds. No human review needed."
        />
      ) : (
        <div className="space-y-4">
          {reviews.map((review: ReviewItem) => (
            <ReviewCard
              key={review.id}
              review={review}
              onApprove={handleApprove}
              onReject={handleReject}
              isActioning={
                actioningId === review.id &&
                (approveMutation.isPending || rejectMutation.isPending)
              }
            />
          ))}
        </div>
      )}

      {total > PAGE_SIZE && (
        <Pagination
          total={total}
          offset={offset}
          limit={PAGE_SIZE}
          onPageChange={setOffset}
          className="mt-6"
        />
      )}
    </div>
  );
};
