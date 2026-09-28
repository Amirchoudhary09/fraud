// Backend-for-frontend proxy: the browser only talks to this origin, and BACKEND_URL is read at
// request time, so one frontend build works against any backend (local, Railway private network).
import type { NextRequest } from "next/server";

const BACKEND = (process.env.BACKEND_URL ?? "https://fraud-backend-v21n.onrender.com").replace(/\/$/, "");
const FORWARD_REQUEST = ["authorization", "content-type", "accept"];
const FORWARD_RESPONSE = ["content-type", "content-disposition", "content-security-policy"];

type Ctx = { params: Promise<{ path: string[] }> };

async function proxy(req: NextRequest, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  const url = `${BACKEND}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  for (const h of FORWARD_REQUEST) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  const ip = req.headers.get("x-forwarded-for");
  if (ip) headers.set("x-forwarded-for", ip);

  const init: RequestInit & { duplex?: "half" } = { method: req.method, headers, redirect: "manual" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = req.body;
    init.duplex = "half"; // required by Node fetch to stream a request body
  }

  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    return Response.json({ detail: "Backend is unreachable. Is the API running?" }, { status: 502 });
  }
  const out = new Headers();
  for (const h of FORWARD_RESPONSE) {
    const v = res.headers.get(h);
    if (v) out.set(h, v);
  }
  return new Response(res.body, { status: res.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
