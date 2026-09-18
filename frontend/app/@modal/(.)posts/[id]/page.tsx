import { notFound } from "next/navigation";
import { Modal } from "@/components/Modal";
import { PostDetail } from "@/components/PostDetail";
import { fetchPost } from "@/lib/api";

export default async function InterceptedPost({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const post = await fetchPost(Number(id));
  if (!post) notFound();
  return <Modal><PostDetail post={post} /></Modal>;
}
