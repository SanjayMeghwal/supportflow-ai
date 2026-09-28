import React, { createContext, useContext, useCallback, useState } from "react";
import { cn } from "@/utils/cn";
import { X } from "lucide-react";

interface Toast {
  id: string;
  title: string;
  description?: string;
  variant: "success" | "error" | "info" | "warning";
  duration?: number;
}

interface ToastContextType {
  toasts: Toast[];
  toast: (opts: Omit<Toast, "id">) => void;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback((opts: Omit<Toast, "id">) => {
    const id = Date.now().toString();
    const t: Toast = { id, duration: 4000, ...opts };
    setToasts((prev) => [...prev, t]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((item) => item.id !== id));
    }, t.duration);
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toasts, toast, dismiss }}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
};

export function useToast(): ToastContextType {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}

const variantStyles = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  error: "border-rose-200 bg-rose-50 text-rose-800",
  info: "border-sky-200 bg-sky-50 text-sky-800",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
};

const ToastContainer: React.FC<{
  toasts: Toast[];
  onDismiss: (id: string) => void;
}> = ({ toasts, onDismiss }) => {
  if (!toasts.length) return null;
  return (
    <div
      aria-live="polite"
      className="fixed bottom-4 right-4 z-50 space-y-2 max-w-sm w-full"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role="alert"
          className={cn(
            "flex items-start gap-3 rounded-xl border p-4 shadow-lg text-sm transition-all",
            variantStyles[t.variant]
          )}
        >
          <div className="flex-1">
            <p className="font-semibold">{t.title}</p>
            {t.description && <p className="mt-0.5 opacity-80">{t.description}</p>}
          </div>
          <button
            onClick={() => onDismiss(t.id)}
            className="mt-0.5 shrink-0 rounded focus:outline-none focus:ring-1 focus:ring-current opacity-60 hover:opacity-100"
            aria-label="Dismiss notification"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ))}
    </div>
  );
};
