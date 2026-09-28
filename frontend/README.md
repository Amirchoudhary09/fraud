# Frontend (Next.js 16, TypeScript)

The browser only talks to this app's own origin:

- `/api/*` is proxied to the backend by `src/app/api/[...path]/route.ts`. `BACKEND_URL` is read at request time.
- `/bff/{login,mfa,setup,refresh,logout}` are session endpoints. The **refresh token is kept only in an httpOnly,
  SameSite=Strict cookie** scoped to `/bff`, so page scripts never see it. They also check the Origin header against CSRF.
  The 15-minute access token lives in memory only.

```
src/
  app/
    login/                   sign in, first-account setup, MFA code step
    (app)/                   protected pages (AppShell layout)
      page.tsx               user dashboard: my searches (who → whom, when, case, purpose), my cases
      searches/              new search, history; [id]: candidates + "Why N?", graph, ask-the-evidence, agent trace
      cases/                 case list/create; [id]: incidents, evidence, searches, timeline, access, reports
      security/              security dashboard, security events, break-glass approvals, audit log + chain verify
      admin/                 users & roles, MFA reset, evaluation, calibration, retention
      account/               MFA (TOTP) enrolment with a locally generated QR code
    api/[...path]/route.ts   backend proxy
    bff/[action]/route.ts    session / refresh-cookie handling
  components/                AppShell, CandidateCard, EvidenceGraph (SVG), ReportViewer (sandboxed iframe),
                             SearchForm, case/{Incidents,Evidence,Access}Panel, ui
  lib/                       api client (typed), auth context, types (mirror backend schemas)
```

```bash
npm install
BACKEND_URL=http://localhost:8000 npm run dev     # http://localhost:3000
npm run build                                     # standalone output for Docker/Railway
npx playwright install chromium && npm run test:e2e   # end-to-end tests
```
