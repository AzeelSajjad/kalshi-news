"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

export function Modal({
  children,
  titleId,
}: {
  children: React.ReactNode;
  titleId?: string;
}) {
  const router = useRouter();
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") router.back();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [router]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={() => router.back()}
      className="fixed inset-0 z-50 overflow-y-auto bg-bg/60 p-6 backdrop-blur-sm"
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        className="relative mx-auto w-fit"
      >
        <button
          type="button"
          onClick={() => router.back()}
          aria-label="Close"
          className="absolute -right-3 -top-3 z-10 flex size-8 items-center justify-center
                     rounded-full border border-border bg-surface-2 text-text hover:border-mint"
        >
          ×
        </button>
        {children}
      </div>
    </div>
  );
}
