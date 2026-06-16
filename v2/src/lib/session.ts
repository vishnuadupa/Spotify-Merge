import { SignJWT, jwtVerify } from "jose";
import { cookies } from "next/headers";

// Use a secret to encrypt the JWT. We use the Spotify Secret as a fallback if SESSION_SECRET isn't set.
const secretKey = process.env.SESSION_SECRET || process.env.SPOTIFY_CLIENT_SECRET || "default_dev_secret_key_32_chars_long!";
const key = new TextEncoder().encode(secretKey);

export interface SessionData {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
}

export async function encrypt(payload: SessionData): Promise<string> {
  return await new SignJWT(payload as any)
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("30d") // session expires in 30 days
    .sign(key);
}

export async function decrypt(input: string): Promise<SessionData | null> {
  try {
    const { payload } = await jwtVerify(input, key, {
      algorithms: ["HS256"],
    });
    return payload as unknown as SessionData;
  } catch (error) {
    return null;
  }
}

export async function getSession(accountLabel: "old" | "new"): Promise<SessionData | null> {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get(`spotify_session_${accountLabel}`)?.value;
  if (!sessionCookie) return null;
  return await decrypt(sessionCookie);
}

export async function setSession(accountLabel: "old" | "new", data: SessionData) {
  const cookieStore = await cookies();
  const encryptedSession = await encrypt(data);
  cookieStore.set(`spotify_session_${accountLabel}`, encryptedSession, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 30 * 24 * 60 * 60, // 30 days
  });
}

export async function clearSession(accountLabel: "old" | "new") {
  const cookieStore = await cookies();
  cookieStore.delete(`spotify_session_${accountLabel}`);
}
