// OIDC single sign-on, browser side.
//   GET /bff/oidc/start     -> asks the backend for the IdP URL, remembers `state` in an httpOnly cookie, redirects.
//   GET /bff/oidc/callback  -> checks `state` against that cookie (blocks login-CSRF), lets the backend verify the
//                              code + id_token, stores the refresh token cookie, and returns to the app.
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

const BACKEND = (process.env.BACKEND_URL ?? "https://fraud-backend-v21n.onrender.com").replace(/\/$/, "");
const STATE_COOKIE = "ie_oidc_state";
const RT_COOKIE = "ie_rt";

type Ctx = { params: Promise<{ step: string }> };

// Relative Location headers: behind a proxy (Railway) the server's own idea of its origin can be an internal
// host name, and a redirect there would land on a different origin than the session cookie.
function redirectSameOrigin(path: string): Response {
  return new Response(null, { status: 302, headers: { Location: path } });
}

function toLogin(error: string): Response {
  return redirectSameOrigin(`/login?${new URLSearchParams({ error: error.slice(0, 200) })}`);
}

async function backend(path: string, body: unknown, req: NextRequest): Promise<Response> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  const ip = req.headers.get("x-forwarded-for");
  if (ip) headers["x-forwarded-for"] = ip;
  return fetch(BACKEND + path, { method: "POST", headers, body: JSON.stringify(body) });
}

export async function GET(req: NextRequest, ctx: Ctx): Promise<Response> {
  const { step } = await ctx.params;
  const jar = await cookies();
  const secure = process.env.NODE_ENV === "production";

  if (step === "start") {
    let res: Response;
    try { res = await backend("/api/auth/oidc/start", {}, req); } catch { return toLogin("Backend is unreachable"); }
    if (!res.ok) return toLogin((await res.json().catch(() => ({}))).detail ?? "Single sign-on is unavailable");
    const { authorization_url } = await res.json();
    const state = new URL(authorization_url).searchParams.get("state") ?? "";
    // Lax (not Strict): the IdP returns with a top-level cross-site navigation, which must carry this cookie.
    jar.set(STATE_COOKIE, state, { httpOnly: true, secure, sameSite: "lax", path: "/bff/oidc", maxAge: 600 });
    return Response.redirect(authorization_url, 302);
  }

  if (step === "callback") {
    const code = req.nextUrl.searchParams.get("code");
    const state = req.nextUrl.searchParams.get("state");
    const expected = jar.get(STATE_COOKIE)?.value;
    jar.set(STATE_COOKIE, "", { path: "/bff/oidc", maxAge: 0 });
    const idpError = req.nextUrl.searchParams.get("error_description") ?? req.nextUrl.searchParams.get("error");
    if (idpError) return toLogin(idpError);
    if (!code || !state || !expected || state !== expected) return toLogin("Sign-in could not be verified. Please try again.");

    let res: Response;
    try { res = await backend("/api/auth/oidc/callback", { code, state }, req); } catch { return toLogin("Backend is unreachable"); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.refresh_token) return toLogin(data.detail ?? "Single sign-on failed");
    jar.set(RT_COOKIE, data.refresh_token, { httpOnly: true, secure, sameSite: "strict", path: "/bff", maxAge: 7 * 24 * 3600 });
    return redirectSameOrigin("/");
  }

  return Response.json({ detail: "Not found" }, { status: 404 });
}
