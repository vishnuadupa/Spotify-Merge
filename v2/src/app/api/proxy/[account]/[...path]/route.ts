import { NextResponse } from "next/server";
import { getSession } from "@/lib/session";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ account: string; path: string[] }> }
) {
  const { account, path } = await params;

  if (account !== "old" && account !== "new") {
    return NextResponse.json({ error: "Invalid account label" }, { status: 400 });
  }

  const session = await getSession(account as "old" | "new");
  if (!session) {
    return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  }

  const spotifyPath = path.join("/");
  const url = new URL(request.url);
  
  // Forward all query parameters (e.g. limit, offset)
  const query = url.search; 

  const spotifyUrl = `https://api.spotify.com/v1/${spotifyPath}${query}`;

  const response = await fetch(spotifyUrl, {
    headers: {
      Authorization: `Bearer ${session.accessToken}`,
    },
  });

  if (!response.ok) {
    // If unauthorized, the token might be expired. For a production app,
    // we would catch the 401 and refresh the token here using refreshAccessToken().
    // For now, we just pass the error back.
    const text = await response.text();
    return NextResponse.json({ error: "Spotify API Error", details: text }, { status: response.status });
  }

  const data = await response.json();
  return NextResponse.json(data);
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ account: string; path: string[] }> }
) {
  const { account, path } = await params;
  if (account !== "old" && account !== "new") return NextResponse.json({ error: "Invalid account label" }, { status: 400 });

  const session = await getSession(account as "old" | "new");
  if (!session) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });

  const body = await request.json();
  const spotifyUrl = `https://api.spotify.com/v1/${path.join("/")}`;

  const response = await fetch(spotifyUrl, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${session.accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  const data = await response.json().catch(() => ({}));
  return NextResponse.json(data, { status: response.status });
}

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ account: string; path: string[] }> }
) {
  const { account, path } = await params;
  if (account !== "old" && account !== "new") return NextResponse.json({ error: "Invalid account label" }, { status: 400 });

  const session = await getSession(account as "old" | "new");
  if (!session) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });

  const body = await request.json().catch(() => null);
  const spotifyUrl = `https://api.spotify.com/v1/${path.join("/")}`;

  const response = await fetch(spotifyUrl, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${session.accessToken}`,
      ...(body && { "Content-Type": "application/json" }),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  const data = await response.json().catch(() => ({}));
  return NextResponse.json(data, { status: response.status });
}
