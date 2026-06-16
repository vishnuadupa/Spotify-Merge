import { NextResponse } from "next/server";
import { getSession } from "@/lib/session";

export async function GET() {
  const oldSession = await getSession("old");
  const newSession = await getSession("new");

  return NextResponse.json({
    old: !!oldSession,
    new: !!newSession,
  });
}
