export const SPOTIFY_CLIENT_ID = process.env.SPOTIFY_CLIENT_ID!;
export const SPOTIFY_CLIENT_SECRET = process.env.SPOTIFY_CLIENT_SECRET!;

const SCOPES = [
  "user-library-read",
  "user-library-modify",
  "playlist-read-private",
  "playlist-read-collaborative",
  "playlist-modify-private",
  "playlist-modify-public",
  "user-follow-read",
  "user-follow-modify",
  "user-read-private",
  "user-read-email"
].join(" ");

/**
 * Returns the exact Redirect URI based on the environment.
 */
export function getRedirectUri(accountLabel: "old" | "new") {
  // Use explicit site URL, fallback to Vercel URL, then localhost
  let baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 
                (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "http://localhost:3000");
  return `${baseUrl}/api/auth/${accountLabel}/callback`;
}

/**
 * Constructs the Spotify OAuth login URL.
 */
export function getAuthUrl(accountLabel: "old" | "new") {
  const params = new URLSearchParams({
    client_id: SPOTIFY_CLIENT_ID,
    response_type: "code",
    redirect_uri: getRedirectUri(accountLabel),
    scope: SCOPES,
    show_dialog: "true" // Force dialog to ensure they log into the right account
  });
  return `https://accounts.spotify.com/authorize?${params.toString()}`;
}

/**
 * Exchanges the code for an access token.
 */
export async function getAccessToken(code: string, accountLabel: "old" | "new") {
  const params = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: getRedirectUri(accountLabel),
  });

  const response = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Authorization: `Basic ${Buffer.from(
        `${SPOTIFY_CLIENT_ID}:${SPOTIFY_CLIENT_SECRET}`
      ).toString("base64")}`,
    },
    body: params.toString(),
  });

  if (!response.ok) {
    throw new Error(`Failed to exchange token: ${await response.text()}`);
  }

  return response.json(); // { access_token, refresh_token, expires_in }
}

/**
 * Refreshes the access token using the refresh token.
 */
export async function refreshAccessToken(refreshToken: string) {
  const params = new URLSearchParams({
    grant_type: "refresh_token",
    refresh_token: refreshToken,
  });

  const response = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Authorization: `Basic ${Buffer.from(
        `${SPOTIFY_CLIENT_ID}:${SPOTIFY_CLIENT_SECRET}`
      ).toString("base64")}`,
    },
    body: params.toString(),
  });

  if (!response.ok) {
    throw new Error("Failed to refresh token");
  }

  return response.json();
}
