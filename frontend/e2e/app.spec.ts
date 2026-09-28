import { expect, test, type Page } from "@playwright/test";
import { createHmac } from "node:crypto";

const ADMIN = { email: "admin@e2e.local", password: "admin-pass-12345" };

/** RFC 6238 TOTP (SHA-1, 30 s, 6 digits), same as the backend and authenticator apps. */
function totp(secretB32: string, at = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secretB32.replace(/=+$/, "")) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)));
  const h = createHmac("sha1", key).update(counter).digest();
  const off = h[h.length - 1] & 0x0f;
  return String((h.readUInt32BE(off) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

async function signIn(page: Page, email = ADMIN.email, password = ADMIN.password) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "My dashboard" })).toBeVisible();
}

test("first account setup creates the super admin", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("heading", { name: "Create the first account" })).toBeVisible();
  await page.getByLabel("Email").fill(ADMIN.email);
  await page.getByLabel("Password", { exact: true }).fill(ADMIN.password);
  await page.getByLabel("Repeat password").fill(ADMIN.password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "My dashboard" })).toBeVisible();
  await expect(page.getByText("super admin", { exact: false }).first()).toBeVisible();

  // the session survives a reload via the httpOnly refresh cookie; no token in web storage
  await page.reload();
  await expect(page.getByRole("heading", { name: "My dashboard" })).toBeVisible();
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
  expect(stored).not.toContain("eyJ");
  const cookies = await page.context().cookies();
  expect(cookies.find((c) => c.name === "ie_rt")?.httpOnly).toBe(true);
});

test("public identity search: candidates, why-score, graph and ask", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: "Searches", exact: true }).click();
  await page.getByLabel("Name *").fill("Amir Choudhary");
  await page.getByLabel("Company").fill("WASP3D");
  await page.getByLabel("College").fill("GLBITM");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Start search" }).click();

  await expect(page.getByRole("tab", { name: /Candidates \(3\)/ })).toBeVisible();
  await page.getByText(/^Why \d+\?$/).first().click();
  await expect(page.locator(".signals").first()).toContainText("company");

  await page.getByRole("tab", { name: "Evidence graph" }).click();
  await expect(page.getByRole("img", { name: "Evidence graph" })).toBeVisible();

  await page.getByRole("tab", { name: "Ask the evidence" }).click();
  await page.getByPlaceholder(/Which sources/).fill("Where does C001 work?");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByRole("heading", { name: "Citations" })).toBeVisible();
});

test("case: incident with comment, evidence integrity, timeline", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: "Cases", exact: true }).click();
  await page.getByText("New case").click();
  await page.getByLabel("Title *").fill("Threatening reply");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page.getByRole("heading", { name: "Threatening reply" })).toBeVisible();

  await page.getByText("Report an incident").click();
  await page.getByLabel(/Original comment text/).fill("you're dead, watch your back");
  await page.getByLabel(/Comment \/ profile URL/).fill("https://x.com/angry_handle/status/1");
  await page.getByRole("button", { name: "Create incident" }).click();
  await expect(page.locator(".badge", { hasText: "THREAT" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Find public profile of @angry_handle" })).toBeVisible();

  await page.getByRole("tab", { name: "Evidence" }).click();
  await page.getByRole("button", { name: "Verify" }).first().click();
  await expect(page.locator(".badge", { hasText: "verified" })).toBeVisible();

  await page.getByRole("tab", { name: "Timeline" }).click();
  await expect(page.getByText(/created an incident/)).toBeVisible();
  await expect(page.getByText(/AI analysis completed/)).toBeVisible();
});

test("MFA enrolment with QR code, then sign-in requires a code", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: "Account" }).click();
  await page.getByRole("button", { name: "Set up MFA" }).click();
  await expect(page.getByRole("img", { name: "MFA QR code" })).toBeVisible();
  const secret = (await page.locator("code").filter({ hasText: /^[A-Z2-7 ]{20,}$/ }).innerText()).replaceAll(" ", "");
  await page.getByLabel("Code").fill(totp(secret));
  await page.getByRole("button", { name: "Confirm and enable" }).click();
  await expect(page.getByText("Two-factor authentication is on")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Email").fill(ADMIN.email);
  await page.getByLabel("Password", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Two-factor code" })).toBeVisible();
  await page.getByLabel(/6-digit code/).fill(totp(secret));
  await page.getByRole("button", { name: "Verify" }).click();
  // back on the page the user signed out from, now authenticated
  await expect(page.getByRole("heading", { name: "Account" })).toBeVisible();
  await expect(page.locator(".badge", { hasText: "enabled" })).toBeVisible();

  // security page: the audit hash chain verifies
  await page.getByRole("link", { name: "Security" }).click();
  await page.getByRole("tab", { name: "Audit log" }).click();
  await page.getByRole("button", { name: "Verify hash chain" }).click();
  await expect(page.getByText(/Chain intact/)).toBeVisible();
});
