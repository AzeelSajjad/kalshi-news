export interface MarketRef {
  ticker: string;
  title: string;
  direction: string;
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
  markets: MarketRef[];
}

export interface PostDetailData extends FeedItem {
  body: string | null;
}

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
