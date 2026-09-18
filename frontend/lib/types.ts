export interface MarketRef {
  ticker: string;
  title: string;
  // The two values the linker emits. Narrowed from `string` so a
  // component branching on direction has an exhaustive set to branch on,
  // and a typo in a test fixture is a type error rather than a silent
  // fall-through to the NO styling.
  direction: "YES" | "NO";
  confidence: number;
  rationale: string;
  yes_price: number | null;
  volume: number | null;
  close_time: string | null;
  price_delta: number | null;
  kalshi_url: string;
}

export interface FeedItem {
  id: number;
  title: string;
  url: string;
  author_name: string | null;
  author_handle: string | null;
  avatar_url: string | null;
  source_kind: string;
  category: string | null;
  published_at: string;
  cluster_size: number;
  // The article's opening prose, stripped of markup at ingest. Null for X
  // posts, whose title already is the text.
  body: string | null;
  markets: MarketRef[];
}

// Identical to FeedItem today. Kept as its own name because /api/posts/{id}
// is where any field too heavy for a 30-item page would land.
export type PostDetailData = FeedItem;

export interface TrendingMarket {
  ticker: string;
  title: string;
  yes_price: number | null;
  volume: number | null;
  post_count: number;
  kalshi_url: string;
}

export interface TrendingPage {
  by_volume: TrendingMarket[];
  most_covered: TrendingMarket[];
}

export interface FeedPage {
  items: FeedItem[];
  next_cursor: string | null;
}
