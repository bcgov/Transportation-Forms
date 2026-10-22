---
id: FEAT-0031
title: Improve Forms CRUD, Statistics, and Audit
owner: Business Analyst
status: draft
created: 2026-09-23 00:00:00
updated: 2026-10-22 13:40:00
depends_on: []
---

# Requirements Index

## User Stories

| ID | Title | Theme |
|---|---|---|
| [US-001](stories/US-001-responsive-form-content-required-business-area.md) | Recompose Add and Edit form content and require Business Area | Form page content and validation |
| [US-002](stories/US-002-add-keywords-with-enter.md) | Add form keywords with Enter | Form authoring efficiency |
| [US-003](stories/US-003-save-pending-edits-before-submit.md) | Save pending edits before submitting for review | Form workflow integrity |
| [US-004](stories/US-004-capture-qualified-form-engagement.md) | Superseded 2026-10-16; split into US-007, US-008, US-009 | Analytics event capture |
| [US-005](stories/US-005-view-form-engagement-statistics.md) | Superseded 2026-10-16; split into US-010, US-011 | Permissioned aggregate insights |
| [US-006](stories/US-006-view-form-activity-history.md) | View form activity history and change details | Permissioned audit accountability |
| [US-007](stories/US-007-persist-daily-engagement-counts.md) | Persist anonymous daily engagement counts within bounded capacity | Analytics count storage |
| [US-008](stories/US-008-count-successful-form-downloads.md) | Count successful form downloads by serving file API | Analytics download capture |
| [US-009](stories/US-009-capture-detail-and-link-engagement-signals.md) | Capture detail views and source-link activations through engagement signals | Analytics signal capture |
| [US-010](stories/US-010-retrieve-authorized-engagement-statistics.md) | Retrieve authorized engagement statistics | Permissioned aggregate service |
| [US-011](stories/US-011-display-engagement-statistics-in-form-insights.md) | Display engagement statistics in Form Insights | Permissioned aggregate presentation |
| [US-012](stories/US-012-require-approved-form-number-on-create.md) | Require an approved form number reservation on new forms | New-form data quality |

Story dependency order for analytics: US-007, then US-008 and US-009 in parallel, then US-010, then US-011. US-012 governs new-form creation separately; US-009 handles grandfathered numberless forms.

## Cross-Cutting Notes

- [Hybrid analytics capture diagram](hybrid-analytics-capture.drawio) predates the Product Owner's 2026-10-22 decisions; US-007 through US-009 take precedence until the diagram is revised by the architecture handoff.
- `docs/mockup-form-insights-edit.html` is the approved form-content reference. FEAT-0031 does not replace the global header, sidebar, navigation, or other Staff portal shell behavior governed by FEAT-0030.
- Add New Form and Edit Form use the approved responsive form-content composition. Form Insights appears only on Edit Form, and its statistics and audit subsections are independently permissioned.
- Business Area is required for create, update, and submit-for-review through both UI and service validation. Only active, non-deleted Business Areas are valid.
- Every new form, including a Draft, requires an approved unused reservation with a usable public number on creation (US-012, Product Owner decision 2026-10-22). Existing numberless forms retain their workflow and Public availability; no new publication check, Edit number-assignment capability, or retroactive migration is added.
- An empty active Business Area catalogue leaves Add/Edit viewable but disables Save and Submit with accessible administrator guidance and no fallback record.
- Keyword Add and Enter share one behavior: trim, compare duplicates case-insensitively, allow 1 through 50 non-control characters, and announce blank, duplicate, or invalid input.
- Enter during IME composition immediately attempts to add the current composed keyword. This Product Owner decision carries an explicit usability risk because Enter commonly confirms an IME candidate.
- Submit for review validates and sequentially saves pending changed values before submitting the exact saved version. Save failure stops submission; submit failure leaves the successful save persisted and the form Draft.
- A version mismatch between save and submit rejects submission, leaves the form Draft, and requires reload/reconciliation.
- Download metrics count authorized full-file Staff or Public GET API handoffs without a `Range` header, including direct API and automated requests. HEAD and ranged GETs are excluded; later Staff streaming, Public edge/storage, or client failure does not reverse a handoff. Existing Staff and Public download audits are unchanged; the proposed additional raw-IP stdout download record was withdrawn on 2026-10-22.
- Detail and link statistics count accepted best-effort signals whose daily writes complete, not verified human actions. UI displays and enabled link activations attempt asynchronous signals; valid direct signals can count without an underlying human action, including automation. A denied UI action sends no signal, but authenticated Staff signals are not checked against that user's form-level access. Raw API reads alone do not count.
- Daily aggregates store one count per form, metric, trusted source, and PCT day in each environment, without individual action rows. Completed concurrent upserts are atomic; capacity refusals are known drops, while timed-out writes can have an unknown commit outcome and are not retried. The user action is never blocked. Bounded stdout summaries group fixed reason codes by time window without visitor or form identity; statistics show no completeness indicator.
- At a healthy peak workload proposed by engineering and approved by the Product Owner, known drops may be at most 10% of writer attempts; uncertain outcomes are measured separately and browser actions never reaching the server are outside that denominator (Product Owner decision 2026-10-22).
- Detail and link UI signals use one dedicated asynchronous endpoint per portal. The Public endpoint uses a separate edge-native, per-replica, approximately 100-attempts-per-minute per trusted client-IP rate with documented burst; valid and invalid attempts both consume the signal budget. This is not a global or exact rolling-window ceiling. The Staff endpoint remains authenticated but has no per-minute limiter.
- Endpoints check matching `Origin` or the parsed origin of `Referer` when `Origin` is absent, accept only an allowed metric and internal form ID (Staff) or existing public form number (Public), reflect no request content, and use the parameterized US-007 writer. A completed increment changes exactly one count; an accepted signal may still be dropped or uncertain. Public form UUIDs are not exposed.
- The valid-form cache is in each pod's memory. Staff pods cache valid internal IDs; Public pods map public form numbers to internal IDs and link state. Numberless legacy Public forms have no signal-cache entry. Pods load at startup, the handling Staff pod updates after commit, and each pod checks changes at its configurable interval (5 minutes by default); no forms-table read occurs per signal. Every failed scheduled check is logged to stdout; a pod keeps its last good cache indefinitely and emits one qualified stale-cache warning at its twentieth consecutive failure, resetting the streak on success. Before its first successful load it rejects signals. Repeated failures can cause indefinite undercounting of new forms and counting of stale forms.
- Writer account (Product Owner confirmed, 2026-10-16): the US-007 writer uses its own dedicated non-superuser database account in every environment, including local, never the application account, limited to insert, update, and the minimum read for the atomic upsert on the daily-count table only, with no delete, truncate, schema change, or ownership, including in local. The database rejects any update that lowers a count. There is no database rule linking counts to forms. Statistics retrieval uses read-only access, never the writer account. See [US-007](stories/US-007-persist-daily-engagement-counts.md) AC8 and BR-010 to BR-013.
- Approved concurrency strategy (2026-10-15, refined 2026-10-22): each completed increment is one parameterized atomic insert-or-increment; analytics writes use a dedicated small pool with short lock and statement timeouts, separate from ordinary operations. Pre-write capacity refusals are known drops, timed-out writes are never retried and may be uncertain; both appear only in bounded summaries. Statistics results remain cached in memory per pod, per environment, form, and period, with a fixed entry cap and least-recently-used eviction until the next PCT midnight; permission and deletion checks still run on every request.
- Capture boundary (Product Owner decision, 2026-10-16): the code that recognizes a qualified engagement (US-008 file APIs, US-009 engagement endpoints) is separate from the code that stores its daily count (US-007 writer). The writer alone assigns the PCT day and persists one increment. This is an internal code boundary only; no queue, broker, or separate service is introduced.
- PCT means fixed UTC-07:00 year-round. Finite statistics windows cover the previous 1, 7, 30, 90, 180, or 365 complete PCT calendar days, ending before today's PCT start.
- TEST collection can start before PROD. All time begins at the current environment's collection start, ends before today's PCT start, requires no historical reconstruction, and discloses its collection start date.
- Daily aggregate counts are retained for the full lifetime of that All time range, without age-based expiration under the current rule. A future retention limit requires a separate decision about the All time reporting range.
- TEST and PROD counts remain separate: no TEST counts are transferred or included in PROD. This needs no TEST-to-PROD data migration, but a new aggregate table may still require a schema migration in each environment.
- `form:stats` and `form:audit` are new standalone effective permissions. Seeded `admin` receives both; seeded `staff_viewer` receives neither; custom roles receive either only through explicit assignment.
- Each new Insights permission independently grants its protected data for every non-deleted form, even when the user lacks `form:read` and `form:edit`. Edit Form access itself remains separately governed by existing rules.
- Unauthorized Edit users see no heading, placeholder, inaccessible message, or protected value for the subsection they lack. Each backing service independently denies unauthorized access.
- Last activity is the newest included saved-change or workflow event and shows event name, snapshotted actor label, and absolute PCT time.
- Audit history shows 10 newest events initially. Load more appends the next 10 without replacement or duplication.
- User-facing audit includes creation, changed-value saves, and successful submit, approve, reject, request-changes, publish, revert, archive, and restore actions. No-op saves, reads, analytics, permission checks, failures, and denials are excluded.
- User actor labels snapshot approved display name, falling back to email only when no display name exists. System activity snapshots `System`. Later profile changes do not rewrite history.
- Required audit-event and actor-snapshot persistence is atomic with its business action. Failure rolls back both.
- Audit rows show changed field names. `View details` is protected by `form:audit` and may show recorded previous/new values, non-empty reasons, and stored attachment object references, but never credentials, signed parameters, or generated download links.
- Launch-forward form audit events are retained indefinitely unless a future approved retention policy supersedes this requirement. The system is pre-production, so no legacy production actor or event reconstruction is required.
- Loading, empty, unavailable, error, Retry, stale-response, accessibility, privacy, desktop, and narrow-mobile behavior is defined in the applicable stories and tests.

## RBAC Matrix

| Capability | Allowed | Denied | Story |
|---|---|---|---|
| Open and use Add New Form | Users with effective `form:create` and existing prerequisites | Users lacking `form:create`; unauthenticated users | [US-001](stories/US-001-responsive-form-content-required-business-area.md) |
| Create a new form with an approved public number | Users with effective `form:create`, an approved unused reservation with usable number, and existing prerequisites | Callers lacking `form:create`; creators without a valid approved unused number | [US-012](stories/US-012-require-approved-form-number-on-create.md) |
| Open and use Edit Form | Users allowed by existing read, edit, ownership, state, and visibility rules | Every user denied by any existing prerequisite; unauthenticated users | [US-001](stories/US-001-responsive-form-content-required-business-area.md) |
| Create, update, or submit without a valid active Business Area | None | All callers through independent UI and service validation | [US-001](stories/US-001-responsive-form-content-required-business-area.md) |
| Add or remove keywords | Users allowed to create or edit the current form | Users denied by permission, ownership, state, or authentication | [US-002](stories/US-002-add-keywords-with-enter.md) |
| Save pending edits and submit a Draft | Draft owner with effective `form:edit` and `form:submit_for_review` plus every existing prerequisite | Non-owner, missing-permission, disallowed-state, and unauthenticated users | [US-003](stories/US-003-save-pending-edits-before-submit.md) |
| Persist daily engagement counts | No user role directly; reached only through US-008 and US-009 qualifying paths (user-facing RBAC not applicable, confirmed by Product Owner 2026-10-16) | Every external caller, including `form:stats` holders | [US-007](stories/US-007-persist-daily-engagement-counts.md) |
| Generate download counts | Users allowed the underlying Staff/Public attachment, including direct file-API callers and automation with full-file GET handoffs | Denied requests, HEAD, ranged GETs, and caller-supplied portal labels | [US-008](stories/US-008-count-successful-form-downloads.md) |
| Generate detail-view and source-link counts | UI sends best-effort signals after allowed actions; authenticated Staff sessions and anonymous same-origin Public clients can submit signals, including automation | Denied UI actions send no signal; unauthenticated Staff signals, origin mismatch, absent cache key, disabled link, and raw non-signal reads produce no count; direct valid Staff signals need not prove form-level access | [US-009](stories/US-009-capture-detail-and-link-engagement-signals.md) |
| Retrieve statistics for any non-deleted form | Authenticated users with effective `form:stats`, including stats-only custom roles | Users lacking `form:stats`, unauthenticated callers, and all callers for deleted/unknown forms | [US-010](stories/US-010-retrieve-authorized-engagement-statistics.md) |
| See statistics on Edit Form | Edit-authorized users with effective `form:stats` | Edit users lacking `form:stats`; users denied Edit Form remain denied the page | [US-011](stories/US-011-display-engagement-statistics-in-form-insights.md) |
| Retrieve audit summary, history, and details for any non-deleted form | Authenticated users with effective `form:audit`, including audit-only custom roles | Users lacking `form:audit`, unauthenticated callers, and all callers for deleted/unknown forms | [US-006](stories/US-006-view-form-activity-history.md) |
| See audit content on Edit Form | Edit-authorized users with effective `form:audit` | Edit users lacking `form:audit`; users denied Edit Form remain denied the page | [US-006](stories/US-006-view-form-activity-history.md) |

## Conflict Resolutions

- **CONFLICT IDENTIFIED (resolved by Product Owner on 2026-10-14, refined 2026-10-22):** An earlier request to prevent direct API downloads conflicts with the existing Public UI file path. Direct authorized full-file GET handoffs, including automation, count under their serving source; HEAD and ranged GETs do not. Direct non-download reads alone do not count. Otherwise-valid automated detail/link signals count under the approved best-effort model.
- **Story split (2026-10-16):** US-004 was split into US-007, US-008, and US-009; US-005 was split into US-010 and US-011. Former IDs below refer to the superseded stories; each superseded file contains a full AC, BR, and test mapping.
- **CONFLICT IDENTIFIED (resolved by Product Owner on 2026-10-22):** The earlier US-004 (now US-008) raw-IP structured stdout record is withdrawn. No new per-download analytics record is emitted; existing Staff and Public download audits and platform logging are unchanged. Daily counts and new analytics summaries remain identity-free.
- **CONFLICT IDENTIFIED (resolved by Product Owner on 2026-10-22):** The intake excludes additional publication rules, but new-form creation now requires an approved unused number under US-012. No publication transition guard or retroactive rule is added. Existing numberless forms keep existing workflow, Public availability, and no Public signal capture without a number.
- **CONFLICT IDENTIFIED (resolved by Product Owner on 2026-09-23):** The mockup marks Business Area required on Edit Form while `00-intake.md` explicitly names Add New Form. The approved rule requires an active, non-deleted Business Area for create, update, and submit-for-review.
- **CONFLICT IDENTIFIED (resolved by Product Owner on 2026-09-23):** `00-intake.md` commits at minimum to latest editor/time while the mockup shows edit history. US-006 expands scope to Last activity, ten-at-a-time recent history, and protected change details.
- **CONFLICT IDENTIFIED (resolved by Product Owner on 2026-09-23):** The mockup includes global shell presentation already governed by FEAT-0030. FEAT-0031 applies only the form-page content and preserves FEAT-0030 global shell behavior.

## Risks / Implementation Handoff

- Standalone `form:stats` and `form:audit` expose protected data for every non-deleted form without `form:read`; architecture and security review must treat this approved scope as sensitive.
- Audit details can contain descriptions, source URLs, reasons, and stored attachment references; response authorization, output encoding, and credential stripping require explicit security validation.
- Current audit rows reference mutable users and current audit writes may not meet actor-snapshot and rollback requirements; implementation must not treat existing behavior as satisfying US-006.
- Daily aggregates cannot replay individual actions; known drops leave statistics below actual activity and timed-out writes may have uncertain outcomes. Bounded standard-output summaries are the only required operational failure signal.
- Existing platform access logs and download audits can still contain IP data; this feature adds no raw-IP per-download log. Existing access, retention, and trusted client-IP controls remain platform/privacy responsibilities, including for the Public signal limiter's trusted client-IP key.
- The proposed bounded direct counter adapter avoids an in-memory queue and broker; its per-action database writes, anonymous Public UI trust, and overload log volume require performance, security, and operational review before approval.
- Daily aggregate storage grows with collection days, forms, metrics, and sources until a future retention policy changes the All time contract.
- Origin and referrer checks are best-effort: a script can forge them and submit counted Public signals for cached forms. Public users sharing a trusted IP key share each edge replica's independent approximate signal-rate budget, which may undercount detail and link activity. Authenticated Staff users can inflate Staff counts without a per-minute limit; the analytics pool ceiling bounds database writes but not the inflated totals.
- The Public NGINX edge needs a POST exception scoped to the engagement endpoint only, with its own rate-limit zone. No Staff rate limiter is required.
- A very popular form's daily count serializes concurrent increments; timed-out writes are not retried because their commit outcome can be uncertain. Sharded counters remain out of scope unless TEST load results show this contention.
- Automation can inflate counts for real forms, limited approximately per trusted IP and edge replica on Public and only by Staff authentication and the analytics pool on Staff. Made-up forms create no rows; row growth is at most 6 per real form per day.
- Forms deleted or made unavailable can keep receiving counts on pods that have not successfully refreshed; newly eligible forms can be missed on those pods. Repeated failed checks can extend both conditions indefinitely despite per-check logs and the warning at failure 20. Counts for deleted forms are retained but never returned.
- A pod whose start-up load and later checks keep failing counts no detail or link activity, with failures visible only in standard-output logs. Operations should watch for these log entries.
- The signed-token approach and its leaked-key risk were withdrawn on 2026-10-16.
- Local deployment grants the application account superuser rights. The Product Owner confirmed on 2026-10-16 that the writer uses its own non-superuser account locally too, with access only to the daily-count table. Local deployment must create that account; this is an engineering handoff outside this plan.
- **CONFLICT IDENTIFIED (resolved by Product Owner on 2026-10-16):** US-011 revocation behavior versus AC8. When `form:stats` is revoked while Edit Form is open and totals are displayed, a denied period change shows the error toast "You do not have permission to view statistics.", reverts the period selector, and keeps the last totals until reload; after reload the section is absent. If no totals were displayed yet, the denial shows the standard AC8 error. AC8 and BR-008 in [US-011](stories/US-011-display-engagement-statistics-in-form-insights.md) were updated; other failures still follow the AC8 error behavior.
- Fixed UTC-07:00 PCT is a feature-specific business timezone and must not be silently replaced by daylight-saving America/Vancouver behavior.
- Immediate keyword add during IME composition may interfere with candidate confirmation and requires Product Owner usability acceptance.
- Playwright acceptance remains pending until the Product Owner deploys the local stack and shares the integrated browser.
