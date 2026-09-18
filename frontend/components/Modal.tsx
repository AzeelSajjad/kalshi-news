"use client";

import { useRouter } from "next/navigation";

export function Modal({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={() => router.back()}
      className="fixed inset-0 z-50 overflow-y-auto bg-black/60 p-6 backdrop-blur-sm"
    >
      <div onClick={(event) => event.stopPropagation()}>{children}</div>
    </div>
  );
}
