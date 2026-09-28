// Minimal OpenID Connect provider for end-to-end tests only (never deploy this).
// /authorize immediately "logs in" a fixed user and redirects back with a code.
import { createHash, createSign, generateKeyPairSync, randomBytes } from "node:crypto";
import { createServer } from "node:http";

const PORT = Number(process.env.IDP_PORT ?? 3899);
const ISSUER = `http://127.0.0.1:${PORT}`;
const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: "jwk" }), kid: "e2e", use: "sig", alg: "RS256" };
const codes = new Map();

const b64 = (b) => Buffer.from(b).toString("base64url");
function sign(claims) {
  const input = `${b64(JSON.stringify({ alg: "RS256", typ: "JWT", kid: "e2e" }))}.${b64(JSON.stringify(claims))}`;
  return `${input}.${createSign("RSA-SHA256").update(input).sign(privateKey).toString("base64url")}`;
}

createServer(async (req, res) => {
  const url = new URL(req.url, ISSUER);
  const json = (code, body) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
  if (url.pathname === "/.well-known/openid-configuration") {
    return json(200, { issuer: ISSUER, authorization_endpoint: `${ISSUER}/authorize`, token_endpoint: `${ISSUER}/token`, jwks_uri: `${ISSUER}/jwks` });
  }
  if (url.pathname === "/jwks") return json(200, { keys: [jwk] });
  if (url.pathname === "/authorize") {
    const code = randomBytes(16).toString("hex");
    codes.set(code, { nonce: url.searchParams.get("nonce"), challenge: url.searchParams.get("code_challenge") });
    const back = new URL(url.searchParams.get("redirect_uri"));
    back.searchParams.set("code", code);
    back.searchParams.set("state", url.searchParams.get("state"));
    res.writeHead(302, { location: back.toString() });
    return res.end();
  }
  if (url.pathname === "/token" && req.method === "POST") {
    let body = "";
    for await (const chunk of req) body += chunk;
    const form = new URLSearchParams(body);
    const entry = codes.get(form.get("code"));
    codes.delete(form.get("code"));
    const verifierOk = entry && createHash("sha256").update(form.get("code_verifier") ?? "").digest("base64url") === entry.challenge;
    if (!verifierOk) return json(400, { error: "invalid_grant" });
    const now = Math.floor(Date.now() / 1000);
    return json(200, {
      token_type: "Bearer", access_token: "x",
      id_token: sign({ iss: ISSUER, aud: form.get("client_id"), sub: "e2e-sso-user", email: "sso@corp.test",
        email_verified: true, name: "SSO User", amr: ["pwd", "mfa"], nonce: entry.nonce, iat: now, exp: now + 300 }),
    });
  }
  if (url.pathname === "/health") return json(200, { ok: true });
  json(404, {});
}).listen(PORT, "127.0.0.1", () => console.log(`fake IdP on ${ISSUER}`));
