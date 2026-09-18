// frontend/app/api/feed/route.ts
import { NextResponse } from "next/server";
import { ApiError, fetchFeed } from "@/lib/api";

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  try {
    const page = await fetchFeed({
      category: params.get("category") ?? undefined,
      cursor: params.get("cursor") ?? undefined,
    });
    return NextResponse.json(page);
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    return NextResponse.json({ error: "feed unavailable" }, { status });
  }
}
