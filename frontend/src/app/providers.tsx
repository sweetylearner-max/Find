"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import { Toaster } from "sonner";
import { vaultStore } from "@/store/vaultStore";

type DesktopBackendStatus =
  | { kind: "starting" }
  | { kind: "ready" }
  | { kind: "failed"; message: string };

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  const [desktopBackendStatus, setDesktopBackendStatus] =
    useState<DesktopBackendStatus | null>(null);
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
          mutations: {
            retry: 1,
          },
        },
      }),
  );

  useEffect(() => {
    const lockFn = () => {
      vaultStore.getState().lock();
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        lockFn();
      }
    };

    window.addEventListener("beforeunload", lockFn);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.removeEventListener("beforeunload", lockFn);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) {
      return;
    }

    let cleanup: (() => void) | undefined;
    let cancelled = false;

    setDesktopBackendStatus({ kind: "starting" });

    import("@tauri-apps/api/event")
      .then(async ({ listen }) => {
        const unlistenReady = await listen("backend-ready", () => {
          setDesktopBackendStatus({ kind: "ready" });
        });
        const unlistenFailed = await listen<string>(
          "backend-failed",
          (event) => {
            setDesktopBackendStatus({
              kind: "failed",
              message: event.payload || "The local backend failed to start.",
            });
          },
        );

        cleanup = () => {
          unlistenReady();
          unlistenFailed();
        };

        if (cancelled) {
          cleanup();
        }
      })
      .catch((error) => {
        setDesktopBackendStatus({
          kind: "failed",
          message:
            error instanceof Error
              ? error.message
              : "Unable to listen for desktop backend status.",
        });
      });

    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {desktopBackendStatus?.kind === "starting" && (
        <div className="fixed right-4 bottom-16 z-50 rounded-full border border-[var(--frost)] bg-[color:var(--frost-soft)] px-4 py-2 text-sm font-medium text-[color:var(--muted)] shadow-lg backdrop-blur-md">
          Starting local backend...
        </div>
      )}
      {desktopBackendStatus?.kind === "failed" && (
        <div className="fixed right-4 bottom-16 z-50 max-w-sm rounded-2xl border border-red-500/40 bg-red-950 px-4 py-3 text-sm text-red-50 shadow-xl">
          <p className="font-semibold">Desktop backend failed to start</p>
          <p className="mt-1 text-red-100">{desktopBackendStatus.message}</p>
        </div>
      )}
      <Toaster position="top-right" richColors theme="system" />
    </QueryClientProvider>
  );
}
