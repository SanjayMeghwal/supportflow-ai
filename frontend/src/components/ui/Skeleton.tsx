import React from "react";
import { cn } from "@/utils/cn";

export const Skeleton: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  ...props
}) => {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-slate-200", className)}
      {...props}
    />
  );
};

export const SkeletonText: React.FC<{ lines?: number } & React.HTMLAttributes<HTMLDivElement>> = ({
  lines = 3,
  className,
}) => {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn("h-4", i === lines - 1 ? "w-3/5" : "w-full")}
        />
      ))}
    </div>
  );
};

export const CardSkeleton: React.FC = () => (
  <div className="rounded-xl border border-slate-200 bg-white p-6 space-y-4">
    <Skeleton className="h-5 w-1/3" />
    <SkeletonText lines={3} />
  </div>
);
