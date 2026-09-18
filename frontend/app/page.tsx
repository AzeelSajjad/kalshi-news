import { Header } from "@/components/Header";
import { PostCard } from "@/components/PostCard";
import { TrendingRail } from "@/components/TrendingRail";
import { EmptyState } from "@/components/EmptyState";
import { NewsletterButton } from "@/components/NewsletterButton";
import { fetchFeed, fetchTrending } from "@/lib/api";

export const revalidate = 60;

export default async function FeedPage({
  searchParams,
}: {
  searchParams: Promise<{ category?: string }>;
}) {
  const { category } = await searchParams;
  const [feed, trending] = await Promise.all([
    fetchFeed({ category }),
    fetchTrending(),
  ]);

  return (
    <div className="relative mx-auto max-w-6xl">
      <Header active={category ?? null} />
      <div className="flex gap-4 p-4">
        <main className="flex-1">
          {feed.items.length === 0
            ? <EmptyState category={category ?? null} />
            : feed.items.map((item) => <PostCard key={item.id} item={item} />)}
        </main>
        <TrendingRail trending={trending} />
      </div>
      <NewsletterButton />
    </div>
  );
}
