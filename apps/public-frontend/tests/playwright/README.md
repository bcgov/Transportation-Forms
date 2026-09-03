# Public-frontend E2E (Playwright) — FEAT-0028 US-004

End-to-end UI tests for the BC Gov public-frontend.

## What is covered

| Spec | Scope |
|---|---|
| `tests/us-004-cms-nav-active.spec.ts` | Defect A — CMS navbar highlights the current page (AC1–AC8). Mocked API. |
| `tests/us-004-form-link.spec.ts` | Defect B — "Form Link" action + external-link icon on home cards and detail view (AC9–AC21). Mocked API. |
| `tests/a11y.spec.ts` | WCAG 2.1 A/AA scans (axe) for home, active CMS page, and link-source detail. Mocked API. |
| `tests/public-frontend-smoke.spec.ts` | Broad smoke of the **live** deployment: header, hero, search, results, view toggle, detail, 404, skip link, console errors. No mocking. |

> The US-004 link-source specs **mock** the public API so they do not depend on
> FEAT-0029 exposing the `url` field. Against the live backend today, CVSE0001
> will render a "Download" action until FEAT-0029 ships.

## Prerequisites

- Node.js 18+.
- A running public-frontend deployment (the Product Owner deploys locally).

## Install (one-time)

```powershell
cd apps/public-frontend/tests/playwright
npm install
npx playwright install
```

## Run

```powershell
# Point at the deployed URL (default shown)
$env:PLAYWRIGHT_BASE_URL = "http://forms-public.localhost/"

# Everything
npm test

# US-004 only (mocked, deterministic)
npm run test:us004

# Live smoke only
npm run test:smoke

# HTML report after a run
npm run report
```

Chromium is the primary target; Firefox and WebKit projects are also configured.
