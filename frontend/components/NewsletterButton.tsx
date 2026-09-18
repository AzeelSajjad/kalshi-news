"use client";

export function NewsletterButton() {
  return (
    <button
      type="button"
      disabled
      title="Coming soon"
      className="fixed bottom-4 right-4 rounded-full bg-mint px-4 py-2.5
                 text-xs font-bold text-bg opacity-90"
    >
      ✉ Join the newsletter
    </button>
  );
}
