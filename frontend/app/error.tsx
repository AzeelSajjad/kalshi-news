"use client";

import { useEffect } from "react";

export default function FeedError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto flex max-w-6xl items-center justify-center px-4 py-24">
      <div className="rounded-xl border border-border bg-surface px-6 py-12 text-center">
        <p className="text-sm font-semibold text-text">The feed is temporarily unavailable</p>
        <p className="mt-1 text-xs text-muted">
          Something went wrong on our end. Please try again in a moment.
        </p>
        <button
          type="button"
          onClick={() => reset()}
          className="mt-4 rounded-md border border-border px-3 py-1.5 text-xs font-semibold text-text hover:border-mint"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
