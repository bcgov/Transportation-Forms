---
id: FEAT-0031
title: Improve Forms CRUD, Statistics, and Audit
owner: Quality Analyst
status: draft
created: 2026-09-23 00:00:00
updated: 2026-10-22 13:40:00
depends_on: []
---

# Test Plan Index

## Coverage Map

| Story | Test File | Acceptance Criteria | Test Cases |
|---|---|---|---|
| [US-001](stories/US-001-responsive-form-content-required-business-area.md) | [TC-US-001](tests/TC-US-001-responsive-form-content-required-business-area.md) | AC1-AC10 | TC 1.1-TC 1.11 |
| [US-002](stories/US-002-add-keywords-with-enter.md) | [TC-US-002](tests/TC-US-002-add-keywords-with-enter.md) | AC1-AC9 | TC 2.1-TC 2.9 |
| [US-003](stories/US-003-save-pending-edits-before-submit.md) | [TC-US-003](tests/TC-US-003-save-pending-edits-before-submit.md) | AC1-AC9 | TC 3.1-TC 3.9 |
| [US-004](stories/US-004-capture-qualified-form-engagement.md) | [TC-US-004](tests/TC-US-004-capture-qualified-form-engagement.md) | Superseded 2026-10-16 | Replaced by TC-US-007, TC-US-008, TC-US-009 |
| [US-005](stories/US-005-view-form-engagement-statistics.md) | [TC-US-005](tests/TC-US-005-view-form-engagement-statistics.md) | Superseded 2026-10-16 | Replaced by TC-US-010, TC-US-011 |
| [US-006](stories/US-006-view-form-activity-history.md) | [TC-US-006](tests/TC-US-006-view-form-activity-history.md) | AC1-AC17 | TC 6.1-TC 6.18 |
| [US-007](stories/US-007-persist-daily-engagement-counts.md) | [TC-US-007](tests/TC-US-007-persist-daily-engagement-counts.md) | AC1-AC9 | TC 7.1-TC 7.12 |
| [US-008](stories/US-008-count-successful-form-downloads.md) | [TC-US-008](tests/TC-US-008-count-successful-form-downloads.md) | AC1-AC9 | TC 8.1-TC 8.12 |
| [US-009](stories/US-009-capture-detail-and-link-engagement-signals.md) | [TC-US-009](tests/TC-US-009-capture-detail-and-link-engagement-signals.md) | AC1-AC18 | TC 9.1-TC 9.34 |
| [US-010](stories/US-010-retrieve-authorized-engagement-statistics.md) | [TC-US-010](tests/TC-US-010-retrieve-authorized-engagement-statistics.md) | AC1-AC12 | TC 10.1-TC 10.20 |
| [US-011](stories/US-011-display-engagement-statistics-in-form-insights.md) | [TC-US-011](tests/TC-US-011-display-engagement-statistics-in-form-insights.md) | AC1-AC12 | TC 11.1-TC 11.15 |
| [US-012](stories/US-012-require-approved-form-number-on-create.md) | [TC-US-012](tests/TC-US-012-require-approved-form-number-on-create.md) | AC1-AC5 | TC 12.1-TC 12.7 |

Every former TC 4.x and TC 5.x case is mapped to its replacement in the superseded test files. New cases added during the split: TC 7.1 (capture boundary), TC 7.4 (PCT day at server receipt), TC 10.3 (permission grant and revocation), and TC 10.4 (period allowlist). TC 9.5 adds a rerender-not-counted assertion from the former US-004 edge case.

New cases added on 2026-10-16 for Product Owner decisions: TC 7.10 (writer account limited to one table, non-superuser in local and TEST), TC 7.11 (database rejects decreases), TC 9.22-TC 9.32 (valid-form cache: per-portal contents and link state, no forms-table read per signal and no growth from made-up forms, no identity, start-up load, start-up failure logged without affecting the application, immediate update on the handling Staff pod after commit, no update on rollback, other pods and Public at the next check, changes outside the application, per-portal interval with 5-minute default, keeping the last good cache on failure), TC 10.19 (counts after deletion retained but never returned), TC 10.20 (statistics never use the writer account), and TC 11.13 (revoked `form:stats`: permission toast, period reverts, last totals kept until reload), and TC 11.14 (revocation before any totals load shows the standard error), and TC 11.15 (permission toast not shown for session expiry, deleted form, or server error; one toast for rapid changes). TC 9.6, TC 9.16, and TC 9.18 were revised for the valid-form cache. The signed-token tests drafted earlier on 2026-10-16 were withdrawn with the token.

2026-10-22 Product Owner decisions add TC 7.12 (at most 10% known drops at an engineering-proposed, Product Owner-approved healthy peak), TC 8.12 (full GET versus HEAD and ranged GET), TC 9.33 (public-number mapping without UUID exposure), TC 9.34 (per-replica trusted-IP limiter), and TC 12.1-TC 12.7 (numbered new forms with legacy grandfathering). TC 7.1 and TC 7.6-TC 7.8 now distinguish bounded summaries, known drops, and uncertain timeouts; TC 8.3 and TC 8.8-TC 8.11 remove new stdout download-record assertions; TC 9.7-TC 9.8, TC 9.12-TC 9.15, TC 9.22, and TC 9.32 reflect best-effort automated signals, edge-native limiting, number mapping, and stale-cache warnings.

## Required Execution Method

- The Product Owner deploys the local stack and shares the integrated browser before acceptance execution begins.
- Every UI and end-to-end case uses Playwright in that shared integrated browser against deployed local Staff and Public endpoints.
- Responsive cases run at desktop and narrow mobile viewport classes in isolated browser contexts.
- Direct service authorization, validation, contract, boundary, lifecycle, and modified-request cases use Playwright `APIRequestContext` against the deployed local API.
- Daily count, environment, role, form, Business Area, workflow, time, response-order, and failure fixtures are isolated per case.
- Script-only inspection, static markup checks, or tests against the unattached mockup do not satisfy deployed acceptance.

## Coverage Requirements

- Every numbered acceptance criterion has at least one mapped deterministic test case.
- Each applicable permission has UI visibility and direct service allow/deny coverage.
- Test `admin`, seeded `staff_viewer`, explicit custom-role grants, missing permission, permission grant/revocation, and unauthenticated behavior.
- Test create, update, submit, valid and invalid Business Areas, empty catalogue, stale association, save failure, submit failure, version conflict, and duplicate activation.
- Test Add and Enter keyword equivalence, trimming, case-insensitive duplicates, blank, 1/50/51-character boundaries, control characters, Unicode, IME composition, locked states, and persistence.
- Test all three engagement metrics for Staff and Public sources, atomic completed daily increments, repeated actions, excluded UI surfaces, direct and automated full-file GET handoffs, excluded HEAD and ranged GETs, late transfer failures, raw reads that send no signal, otherwise-valid automated detail/link signals, unchanged existing download audits without a new raw-IP record, known drops versus uncertain timeouts, privacy, denied UI actions versus valid direct Staff signals, and isolated TEST/PROD counts.
- Test the dedicated engagement endpoints: non-blocking UI signals, the Public edge-native per-replica approximately 100-attempts-per-minute rate and documented burst for every valid/invalid attempt, Staff with no per-minute limit, trusted-IP keying, rate isolation from ordinary Public access, parsed-origin/referrer matching, malformed and malicious bodies, no reflected content, public-number-to-internal-ID mapping without UUID disclosure, numberless legacy exclusion, valid-form cache behavior (made-up forms rejected in memory, start-up failure, immediate post-commit update, configurable change checks, indefinitely retained last good cache, per-check failure logs, one warning at failure 20 per pod/streak), single completed-count changes, Staff authentication, atomic first-of-day upserts, writer account privileges, database rejection of decreases, pool isolation and known/uncertain outcomes, and statistics cache access checks. Run rate-limit and load cases only in local or TEST.
- Test the new-form approved unused number requirement in UI and direct create service, legacy numberless form workflows without an added publication check, and accessible correction on narrow screens. At the approved healthy peak, measure known drops divided by writer attempts at no more than 10%; report uncertain outcomes separately and do not claim browser delivery rates.
- Test all seven statistics periods, complete previous-day fixed UTC-07:00 boundaries, 365-day year, each environment's collection start, lifetime All time count retention beyond one year, six-value aggregation, PCT data-through date, zero, loading, unavailable, error, Retry, stdout-only telemetry failure, stale responses, and deleted/unknown forms.
- Test audit latest activity, 0/1/10/11/25-event boundaries, Load more, approved event catalogue, no-op save exclusion, actor snapshots, profile changes, PCT time, detail disclosure, credential stripping, atomic rollback, states, and deleted/unknown forms.
- Run accessibility checks for keyboard operation, visible focus, accessible names, live status, validation summary links, selected state, modal focus containment/return, non-colour labels, reading order, and responsive geometry.

## Regression Map

- Re-run FEAT-0025 Business Area administration, lifecycle, and authorization coverage.
- Re-run FEAT-0030 global shell, Edit access, form drawer, live authorization, empty catalogue, and responsive coverage.
- Re-run existing form create, update, source URL, attachment, keyword, public flag, personal-information, effective-date, ownership, and workflow suites.
- Re-run Staff and Public form-detail, link, and download behavior because they now increment qualified daily counts.
- Re-run every successful included form action because required audit persistence is now part of transaction success.

## Execution Status

- **Status:** Not executed.
- **Blocker:** Product Owner must deploy the local stack and share the integrated browser.
- **Acceptance:** FEAT-0031 is not test-complete until all mapped Playwright UI and APIRequestContext cases pass against that deployment.
