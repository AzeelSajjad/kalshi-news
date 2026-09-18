import Link from "next/link";

// Derived from the seeded source registry, not from what a feed *could*
// plausibly cover: backend/migrations/versions/0002_seed_sources.py is the
// only thing that creates sources, and backend/app/jobs/ingest.py sets
// post.category = source.category unconditionally, so the set of categories
// a post can ever carry is exactly the set on enabled source rows.
//
// Enabled today: Politico Politics + Bloomberg Politics (Politics),
// Politico Economy + CNBC Economy (Economics), Bloomberg Markets + CNBC Top
// News (Finance), and the X source (World). Reuters and AP are the only
// other World rows and are seeded disabled -- neither serves a public RSS
// feed any more, so they are left disabled rather than re-enabled here.
//
// Crypto, Sports and Culture had no source behind them and rendered "No
// stories yet" permanently. Adding a tab back means seeding a source for it
// first.
export const CATEGORIES = [
  "Politics", "Economics", "Finance", "World",
] as const;

function tabClass(isActive: boolean) {
  return isActive
    ? "rounded-md bg-mint px-2.5 py-1.5 text-[12.5px] font-semibold text-bg"
    : "rounded-md px-2.5 py-1.5 text-[12.5px] text-muted hover:text-text";
}

export function Header({ active }: { active: string | null }) {
  return (
    <header className="flex items-center gap-4 border-b border-border bg-surface px-4 py-2.5">
      <nav className="flex flex-1 gap-1 overflow-x-auto">
        <Link href="/" className={tabClass(active === null)}
              aria-current={active === null ? "page" : undefined}>
          All
        </Link>
        {CATEGORIES.map((category) => (
          <Link
            key={category}
            href={`/?category=${category}`}
            className={tabClass(active === category)}
            aria-current={active === category ? "page" : undefined}
          >
            {category}
          </Link>
        ))}
      </nav>

      <div data-testid="kalshi-attribution" className="shrink-0">
        <a
          href="https://kalshi.com"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 rounded-lg border border-border bg-surface-2
                     px-3 py-1.5 text-xs font-semibold"
        >
          <span className="size-4 rounded bg-mint" aria-hidden />
          Kalshi <span className="font-normal text-muted">↗</span>
        </a>
      </div>
    </header>
  );
}
