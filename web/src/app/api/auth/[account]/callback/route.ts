import { NextResponse } from "next/server";
import { getAccessToken } from "@/lib/spotify";
import { setSession } from "@/lib/session";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ account: string }> }
) {
  const account = (await params).account;
  if (account !== "old" && account !== "new") {
    return NextResponse.json({ error: "Invalid account label" }, { status: 400 });
  }

  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const error = url.searchParams.get("error");

  if (error || !code) {
    return NextResponse.redirect(new URL("/?error=auth_failed", request.url));
  }

  try {
    const data = await getAccessToken(code, account as "old" | "new");
    
    // Encrypt and store the tokens in a secure HTTP-only cookie
    await setSession(account as "old" | "new", {
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
      expiresAt: Date.now() + data.expires_in * 1000,
    });

    return NextResponse.redirect(new URL("/", request.url));
  } catch (err) {
    console.error(err);
    return NextResponse.redirect(new URL("/?error=token_exchange_failed", request.url));
  }
}
