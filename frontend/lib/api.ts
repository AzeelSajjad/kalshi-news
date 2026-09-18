import type { FeedPage, PostDetailData, TrendingPage } from "./types";

export class ApiError extends Error {
  constructor(readonly status: number, path: string) {
    super(`backend responded ${status} for ${path}`);
    this.name = "ApiError";
  }
}

function base(): string {
  const url = process.env.BACKEND_API_URL;
  if (!url) throw new Error("BACKEND_API_URL is not set");
  return url.replace(/\/$/, "");
}

async function get<T>(path: string, params?: Record<string, string | number | undefined>) {
  const url = new URL(`${base()}${path}`);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  const response = await fetch(url, { next: { revalidate: 60 } });
  if (!response.ok) throw new ApiError(response.status, path);
  return (await response.json()) as T;
}

export function fetchFeed(opts: { category?: string; limit?: number; cursor?: string } = {}) {
  return get<FeedPage>("/api/feed", opts);
}

export async function fetchPost(id: number): Promise<PostDetailData | null> {
  const response = await fetch(`${base()}/api/posts/${id}`, { next: { revalidate: 60 } });
  if (response.status === 404) return null;
  if (!response.ok) throw new ApiError(response.status, `/api/posts/${id}`);
  return (await response.json()) as PostDetailData;
}

export function fetchTrending(limit?: number) {
  return get<TrendingPage>("/api/trending", { limit });
}
