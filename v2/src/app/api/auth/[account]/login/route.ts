import { NextResponse } from "next/server";
import { getAuthUrl } from "@/lib/spotify";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ account: string }> }
) {
  const account = (await params).account;
  if (account !== "old" && account !== "new") {
    return NextResponse.json({ error: "Invalid account label" }, { status: 400 });
  }

  const url = getAuthUrl(account as "old" | "new");
  return NextResponse.redirect(url);
}
