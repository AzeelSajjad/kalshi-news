import Link from "next/link";

export const CATEGORIES = [
  "Politics", "Economics", "Finance", "World", "Crypto", "Sports", "Culture",
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
