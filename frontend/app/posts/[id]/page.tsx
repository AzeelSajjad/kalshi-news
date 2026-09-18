import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Header } from "@/components/Header";
import { NewsletterButton } from "@/components/NewsletterButton";
import { PostDetail } from "@/components/PostDetail";
import { TrendingRail } from "@/components/TrendingRail";
import { fetchPost, fetchTrending } from "@/lib/api";

export const revalidate = 60;

const MAX_DESCRIPTION = 200;

type Params = { params: Promise<{ id: string }> };

/**
 * The whole argument for intercepting routes is that a story is shareable,
 * so the shared destination is a first-class page, not a bare card on a
 * black background: it carries the same shell the feed does — the category
 * tabs, the Kalshi attribution, the trending rail — and an explicit route
 * back in. Someone who arrives here from a pasted link should land in the
 * product, not at a dead end.
 */
export default async function PostPage({ params }: Params) {
  const { id } = await params;
  const [post, trending] = await Promise.all([
    fetchPost(Number(id)),
    fetchTrending(),
  ]);
  if (!post) notFound();

  return (
    <div className="relative mx-auto max-w-6xl">
      <Header active={post.category ?? null} />
      <div className="flex gap-4 p-4">
        <main className="flex-1">
          <Link
            href="/"
            data-testid="back-to-feed"
            className="mb-3 inline-block text-xs font-semibold text-muted hover:text-text"
          >
            ← Back to the feed
          </Link>
          <PostDetail post={post} />
        </main>
        <TrendingRail trending={trending} />
      </div>
      <NewsletterButton />
    </div>
  );
}

/**
 * A pasted link is this product's delivery mechanism, so what the link
 * unfurls into is part of the product. Without this every story previewed as
 * the generic site title, which makes ten shared stories look like ten
 * copies of the same one.
 */
export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { id } = await params;
  const post = await fetchPost(Number(id)).catch(() => null);
  if (!post) return {};

  const description = truncate(post.body ?? post.title, MAX_DESCRIPTION);
  return {
    title: post.title,
    description,
    openGraph: {
      type: "article",
      title: post.title,
      description,
      url: `/posts/${post.id}`,
    },
    twitter: { card: "summary_large_image", title: post.title, description },
  };
}

function truncate(text: string, limit: number): string {
  const clean = text.trim();
  if (clean.length <= limit) return clean;
  // Cut on a word boundary so the preview does not end mid-word.
  const cut = clean.slice(0, limit - 1);
  const lastSpace = cut.lastIndexOf(" ");
  return `${(lastSpace > limit / 2 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}
