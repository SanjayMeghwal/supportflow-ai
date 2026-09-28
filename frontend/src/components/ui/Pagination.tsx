import React from "react";
import { cn } from "@/utils/cn";
import { Button } from "./Button";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  total: number;
  offset: number;
  limit: number;
  onPageChange: (offset: number) => void;
  className?: string;
}

export const Pagination: React.FC<PaginationProps> = ({
  total,
  offset,
  limit,
  onPageChange,
  className,
}) => {
  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.ceil(total / limit);

  if (totalPages <= 1) return null;

  const start = offset + 1;
  const end = Math.min(offset + limit, total);

  return (
    <div
      className={cn("flex items-center justify-between gap-4 text-sm", className)}
    >
      <p className="text-slate-500">
        Showing{" "}
        <span className="font-medium text-slate-700">{start}</span>–
        <span className="font-medium text-slate-700">{end}</span> of{" "}
        <span className="font-medium text-slate-700">{total}</span>
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(Math.max(0, offset - limit))}
          disabled={currentPage === 1}
          leftIcon={<ChevronLeft className="w-3.5 h-3.5" />}
          aria-label="Previous page"
        >
          Prev
        </Button>
        <span className="px-3 text-slate-600">
          {currentPage} / {totalPages}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(offset + limit)}
          disabled={currentPage === totalPages}
          rightIcon={<ChevronRight className="w-3.5 h-3.5" />}
          aria-label="Next page"
        >
          Next
        </Button>
      </div>
    </div>
  );
};
