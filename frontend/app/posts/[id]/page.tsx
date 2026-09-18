import { notFound } from "next/navigation";
import { PostDetail } from "@/components/PostDetail";
import { fetchPost } from "@/lib/api";

export const revalidate = 60;

export default async function PostPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const post = await fetchPost(Number(id));
  if (!post) notFound();
  return <div className="p-6">
    <PostDetail post={post} />
  </div>;
}
