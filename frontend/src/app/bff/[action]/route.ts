// Session endpoints (backend-for-frontend). The refresh token lives only in an httpOnly,
// SameSite=Strict cookie scoped to /bff, so page JavaScript (and any XSS) can never read it.
// The short-lived access token is returned to the page and kept in memory only.
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

const BACKEND = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
const COOKIE = "ie_rt";
const UPSTREAM: Record<string, string> = {
  login: "/api/auth/login",
  mfa: "/api/auth/login/mfa",
  setup: "/api/auth/setup",
  refresh: "/api/auth/refresh",
  logout: "/api/auth/logout",
};

type Ctx = { params: Promise<{ action: string }> };

function sameOrigin(req: NextRequest): boolean {
  // CSRF defence in addition to SameSite=Strict: browsers always send Origin on POST.
  const origin = req.headers.get("origin");
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host");
  return !!origin && !!host && new URL(origin).host === host;
}

export async function POST(req: NextRequest, ctx: Ctx): Promise<Response> {
  const { action } = await ctx.params;
  const path = UPSTREAM[action];
  if (!path) return Response.json({ detail: "Not found" }, { status: 404 });
  if (!sameOrigin(req)) return Response.json({ detail: "Cross-origin request blocked" }, { status: 403 });

  const jar = await cookies();
  let body: string;
  if (action === "refresh" || action === "logout") {
    const rt = jar.get(COOKIE)?.value;
    if (!rt) return Response.json({ detail: "No session" }, { status: 401 });
    body = JSON.stringify({ refresh_token: rt });
  } else {
    body = await req.text();
  }

  const headers: Record<string, string> = { "content-type": "application/json" };
  const ip = req.headers.get("x-forwarded-for");
  if (ip) headers["x-forwarded-for"] = ip;
  let res: Response;
  try {
    res = await fetch(BACKEND + path, { method: "POST", headers, body });
  } catch {
    return Response.json({ detail: "Backend is unreachable. Is the API running?" }, { status: 502 });
  }
  const data = await res.json().catch(() => ({}));

  if (action === "logout" || (action === "refresh" && !res.ok)) jar.set(COOKIE, "", { path: "/bff", maxAge: 0 });
  if (res.ok && data.refresh_token) {
    jar.set(COOKIE, data.refresh_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      path: "/bff",
      maxAge: 7 * 24 * 3600,
    });
    delete data.refresh_token;
  }
  return Response.json(data, { status: res.status });
}
