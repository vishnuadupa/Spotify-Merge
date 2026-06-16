# Spotify Web API — Binding Development Rules

**Effective:** 2026-06-15  
**Applies to:** All Spotify API integration work on this project

## 1. Specification Authority
- **Source of truth:** https://developer.spotify.com/reference/web-api/open-api-schema.yaml
- Never guess endpoint paths, parameters, or response schemas
- Validate all implementations against the OpenAPI spec

## 2. Authorization & Authentication

### Flow Selection
- **User-specific data:** Authorization Code with PKCE flow (https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow) — **preferred**
- **With secure backend:** Authorization Code flow (https://developer.spotify.com/documentation/web-api/tutorials/code-flow) — acceptable
- **Public/non-user data only:** Client Credentials flow
- **NEVER:** Implicit Grant flow (deprecated)

### Redirect URIs
- **Production:** HTTPS only (no exceptions)
- **Local development:** `http://127.0.0.1:PORT` (only exception to HTTPS rule)
- **Never:** `http://localhost`, wildcard URIs (`*`), or non-standard protocols
- Reference: https://developer.spotify.com/documentation/web-api/concepts/redirect_uri

### Token Management
- Store access/refresh tokens securely (never in frontend code, browser storage, or version control)
- Implement token refresh logic (https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens)
- Never expose Client Secret in client-side code
- Handle token expiration gracefully

## 3. Scopes

- Request **minimum scopes only** needed for current features
- Do not request broad scopes preemptively ("just in case")
- Reference: https://developer.spotify.com/documentation/web-api/concepts/scopes
- Validate against OpenAPI spec for required scopes per endpoint

## 4. Rate Limiting & Resilience

- **Rolling 30-second window** (no published cap, community ~180 req/30s in dev)
- **On HTTP 429:** Respect `Retry-After` header, implement exponential backoff
- **Never:** Retry immediately, poll in tight loops, or ignore rate limit headers
- Implement proactive throttling to avoid hitting limits
- Handle 429 + 5xx errors with exponential backoff (max 8 retries recommended)

## 5. Endpoint Preferences (Deprecated Alternatives)

| Use This | Not This | Reason |
|----------|----------|--------|
| `/playlists/{id}/items` | `/playlists/{id}/tracks` | Official spec |
| `/me/library` | `/me/albums`, `/me/tracks`, `/me/shows` (type-specific) | Unified endpoint |

## 6. Endpoints Not Available (Deprecated 2024-11-27)

The following return **403 Forbidden** for new apps (no replacement, no waitlist):
- `/v1/audio-features` and `/v1/audio-analysis`
- `/v1/recommendations`
- `/v1/artists/{id}/related-artists`
- `/v1/browse/featured-playlists` and `/v1/browse/categories/{id}/playlists`
- 30s preview URLs

**Do not use.** Use alternatives (e.g., `/artists/{id}` for genres, `/me/top/tracks` for ranking).

## 7. Error Handling

- Handle **all HTTP codes** documented in the OpenAPI schema
- Read and use the returned error message for user feedback
- Log errors for debugging (redact tokens and sensitive data)
- Provide meaningful, actionable feedback to users

## 8. Developer Terms of Service Compliance

**Reference:** https://developer.spotify.com/terms

- **Caching:** Cache Spotify content **only as needed for immediate use.** Do not build a long-term cache without user consent.
- **Attribution:** Always attribute content to Spotify in the UI
- **ML/Training:** Do not use the API to train machine learning models on Spotify data
- **Rate limits:** Respect rate limits; do not attempt circumvention
- **Terms updates:** Check Spotify Developer Terms regularly for policy changes

## 9. Implementation Checklist

Before deploying:
- [ ] All endpoints validated against OpenAPI spec
- [ ] OAuth flow matches rules (PKCE for public clients, Code for secure backends)
- [ ] Token storage is secure (backend, encrypted, never frontend)
- [ ] Token refresh implemented and tested
- [ ] Rate limit handling tested (mock 429 responses)
- [ ] All error codes from spec are handled
- [ ] Redirect URIs are HTTPS (or http://127.0.0.1 for local dev)
- [ ] Scopes are minimal for features implemented
- [ ] Spotify attribution present in UI
- [ ] No deprecated endpoints in use
- [ ] No ML training on Spotify data
- [ ] Terms of Service acknowledged and understood
