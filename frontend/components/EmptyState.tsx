export function EmptyState({ category }: { category: string | null }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-6 py-12 text-center">
      <p className="text-sm font-semibold">No stories yet</p>
      <p className="mt-1 text-xs text-muted">
        {category
          ? `Nothing filed under ${category} in the current window.`
          : "The feed fills as stories are ingested and linked to markets."}
      </p>
    </div>
  );
}
