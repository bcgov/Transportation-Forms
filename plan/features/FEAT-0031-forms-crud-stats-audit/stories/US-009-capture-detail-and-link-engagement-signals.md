---
feature_id: FEAT-0031
story_id: US-009
title: Capture detail views and source-link activations through engagement signals
owner: Business Analyst
status: draft
created: 2026-10-16 13:30:00
updated: 2026-10-22 13:40:00
depends_on: [US-007, FEAT-0029, FEAT-0030-US-008]
---

# User Story

As a Product Owner, I want form-detail displays and enabled source-link activations reported to protected engagement endpoints, so that best-effort signal counts are attributed by portal without slowing users or allowing garbage writes.

# Preconditions / Assumptions

- Split from former US-004 on 2026-10-16. This story owns detail-view and source-link qualification and the Staff and Public engagement endpoints. Count persistence is owned by [US-007](US-007-persist-daily-engagement-counts.md). Downloads are owned by [US-008](US-008-count-successful-form-downloads.md).
- Detail-view and source-link signals are sent asynchronously from the portal UI to a dedicated engagement endpoint in each portal (Product Owner decision, 2026-10-15).
- Source for detail views and link activations is the portal whose dedicated engagement endpoint receives the signal; request referrer and caller-supplied labels are not attribution rules.
- The Product Owner approved dropping detail/link signals that exceed the Public limit on 2026-10-15. Dropped signals can undercount but never affect the user action.
- Valid-form cache (Product Owner decisions, 2026-10-16, replacing the earlier signed engagement token, which is withdrawn): each Staff backend pod caches valid internal form IDs and each Public backend pod caches public form numbers mapped to internal form IDs; both record enabled valid source-link state. The Public API does not expose internal form UUIDs. The endpoint checks signals in memory, so no forms-table read occurs per signal and the only database statement caused by a counted signal is the US-007 increment.
- The cache is kept current by three mechanisms, in this order: (1) load at pod start-up; (2) immediate update on the Staff pod that saves any form change, after the change is committed; (3) a change check on every Staff and Public pod at a fixed interval, set separately for each portal by an environment variable, defaulting to 5 minutes when blank (Product Owner decision, 2026-10-16).
- A start-up load failure is logged to container standard output, and the pod continues to start and serve all other operations normally (Product Owner decision, 2026-10-16).
- No database rule links daily counts to the forms table (Product Owner decision, 2026-10-16). The valid-form cache is the control that prevents counts for made-up forms.
- The existing Public form-list response cache (up to 5 minutes) is unchanged.
- Existing Staff and Public portal permissions, form visibility, detail display, and configured source actions remain authoritative.
- Product Owner decisions on 2026-10-22: counts represent accepted best-effort signals, including otherwise-valid automated signals; Public signal limiting is per edge replica and applies to all attempts, not just accepted signals; a stale cache stays in use indefinitely with per-check failure logs and one warning at the twentieth consecutive failure per pod.
- Security controls follow OWASP ASVS, API Security Top 10 2023 (API4 Unrestricted Resource Consumption), and the Cheat Sheet Series for Input Validation, SQL Injection Prevention and Query Parameterization, Cross-Site Request Forgery Prevention (standard-header origin verification), Cross-Site Scripting Prevention, REST Security, Logging, and Denial of Service. Relevant weaknesses are CWE-89, CWE-79, CWE-117, and CWE-770.

# Test Coverage

- [TC-US-009 Capture detail and link engagement signals](../tests/TC-US-009-capture-detail-and-link-engagement-signals.md)

# Acceptance Criteria

## AC1 - Enabled source-link activations are counted

**Given** a Staff or Public portal UI exposes an enabled, valid configured external URL  
**When** the portal accepts an activation and initiates navigation  
**Then** it attempts one asynchronous source-link-click signal; each accepted, successfully written signal increments the daily count by one for that form and receiving portal  
**And** copied URLs, browser/direct navigation, invalid links, disabled links, and raw API reads do not themselves send a signal  
**And** a source-link-click signal is accepted only when the receiving pod's valid-form cache records an enabled, valid source link for that form (AC15)  
**And** a directly submitted valid signal may count without a real activation, while a lost, rejected, or dropped UI signal may leave a real activation uncounted; neither signal acceptance nor counting asserts that the external site loaded.

## AC2 - Successful detail displays are counted

**Given** a user is allowed to view a form  
**When** the Staff form-details drawer or the Public form-detail page successfully displays that form  
**Then** that UI attempts one asynchronous detail-view signal; each accepted, successfully written signal increments the daily count by one for that form and receiving portal  
**And** Add New Form, Edit Form, form cards, raw API reads, previews, Form Insights displays, and failed displays do not themselves send detail-view signals  
**And** an accepted direct signal does not prove that a detail was displayed.

## AC3 - Every qualified repeated detail or link action is counted

**Given** the same person or browser session performs the same qualified detail view or source-link activation more than once  
**When** each action independently meets its metric definition  
**Then** each accepted, successfully written signal adds one to the corresponding daily count, subject to US-007 capacity and timeout rules  
**And** no person-level or session-level deduplication is applied  
**And** reopening a closed details surface is another qualified view, while rerendering an already open surface without a new user open action is not.

## AC4 - Detail and link source is the receiving endpoint and cannot be spoofed

**Given** a detail view or source-link activation is reported  
**When** its daily count is updated  
**Then** it is attributed to the portal whose engagement endpoint received the accepted signal  
**And** raw API reads and other direct non-signal requests are excluded  
**And** a caller cannot relabel one portal's activity as the other portal through an untrusted request value.

## AC5 - Accepted signals are not classified by human or bot status

**Given** a signal comes from human Staff preview/test use, a Public client, or identifiable automation  
**When** it passes the same endpoint, cache, and rate-limit checks  
**Then** it is eligible for exactly one count-write attempt regardless of traffic classification  
**And** recognized crawlers that receive server-rendered metadata instead of the portal UI send no UI signal, but a valid direct signal from automation is not rejected for being automated.

## AC6 - Existing portal authorization remains authoritative

**Given** a user is denied the underlying form detail or source action under existing rules, or the form is unavailable to that portal  
**When** the user attempts that action  
**Then** the existing denial remains in effect  
**And** the denied or failed UI action sends no signal and generates no count by itself  
**And** an independently submitted, otherwise-valid Staff signal for a cached form can still count even when its authenticated sender lacks access to that form; the endpoint does not prove the underlying action or check form-level Staff access.

## AC7 - Signal or count failure does not block the user action

**Given** a detail display or source-link activation otherwise succeeds  
**When** its signal is lost or rejected, or its count increment fails under US-007  
**Then** the detail display or navigation still succeeds  
**And** no telemetry-failure notification is shown to the user.

## AC8 - Detail and link signals use a dedicated asynchronous endpoint

**Given** a Staff or Public portal UI has qualified a detail view or source-link activation  
**When** it reports that action  
**Then** it attempts exactly one signal, containing its permitted form identifier and the metric, to that portal's dedicated engagement endpoint without waiting for a response before displaying the form or starting navigation  
**And** the endpoint accepts only detail-view and source-link-click signals  
**And** download and unknown-metric signals sent to the endpoint are rejected without a count.

## AC9 - Separate Public rate-based limit protects ordinary access

**Given** an edge replica receives Public engagement requests from one trusted client-IP key  
**When** their rate exceeds that replica's dedicated approximately 100-attempts-per-minute rate with a bounded, documented burst allowance  
**Then** excess attempts, including otherwise-invalid or rejected signals, are limited before signal validation or database work and are not counted  
**And** neither accepted nor rejected signals consume the ordinary Public portal or API rate-limit budgets, so the client's next ordinary form request is not rejected because of signal volume  
**And** the user's detail display or navigation still succeeds with no notification  
**And** each Public edge replica has its own budget, not a deployment-wide or exact rolling-60-second ceiling; the Staff engagement endpoint has no per-minute signal limit and relies on Staff authentication (AC13) and the analytics database ceiling (US-007 AC6).

## AC10 - Origin and referrer must match the receiving portal

**Given** a signal arrives at a dedicated engagement endpoint  
**When** its `Origin` header, or the parsed origin of its `Referer` URL when `Origin` is absent, does not match the receiving portal's own scheme, host, and port, or both headers are absent  
**Then** the signal is rejected without a count  
**And** a matching origin is treated as a best-effort browser check, not as proof of human use or as authentication.

## AC11 - Strict input allowlist and no reflected content

**Given** a signal body  
**When** it is anything other than one well-formed internal form ID for Staff or existing public form number for Public and one allowed metric, including extra fields, script or markup, SQL fragments, control characters, malformed or oversized content, a wrong content type, or caller-supplied count, date, source, IP, or portal values  
**Then** it is rejected without a count or any database read or write  
**And** every endpoint response, accepted or rejected, contains no request-supplied value and cannot be rendered as executable content  
**And** rejection logs contain only server-defined reason codes, never raw request content.

## AC12 - Accepted signals cannot write garbage or alter other data

**Given** a well-formed signal passes origin and input validation  
**When** it is processed  
**Then** it reaches the writer only if its identifier is in the receiving pod's valid-form cache, with a Public form number resolved in memory to its internal form ID  
**And** a successfully written increment changes exactly one daily count by exactly one, using the cached internal form ID, the receiving portal, the server-validated metric, and the server-determined PCT day; an accepted signal may still be dropped or have an uncertain write outcome under US-007  
**And** a signal for a made-up form identifier never creates or changes a count  
**And** a signal for a form not in the receiving pod's last good cache, including a never-loaded deleted form or, on the Public endpoint, a form not publicly available when last checked or lacking a form number, is rejected without a count and without any database read or write  
**And** no forms-table or other database read is performed to validate the signal  
**And** the endpoint cannot read other data, decrement, reset, delete, or alter any record or schema.

## AC13 - Staff signals require an authenticated Staff session

**Given** a signal arrives at the Staff engagement endpoint  
**When** it has no valid, unexpired Staff authentication  
**Then** it is rejected without a count, using the existing Staff authentication rules  
**And** authenticated Staff signals remain subject to AC10-AC12 and US-007 AC6 but not to a per-minute limit  
**And** the Public endpoint requires no authentication but remains subject to AC9-AC12 and US-007 AC6.

## AC14 - New signal output contains no visitor identity

**Given** a signal is accepted, rejected, or rate-limited  
**When** new engagement-endpoint logs and responses are inspected  
**Then** they contain no visitor name, email, account identifier, IP address, user-agent, screen resolution, or other unnecessary personal information  
**And** no new per-download engagement stdout record is produced under US-008; existing platform and download audit logs remain unchanged.

## AC15 - Each pod holds a valid-form cache for its portal

**Given** a Staff or Public backend pod is running  
**When** its valid-form cache is populated  
**Then** a Staff pod's cache contains internal IDs for non-deleted forms, and a Public pod's cache maps public form numbers of available forms to internal form IDs; numberless legacy Public forms have no signal-cache entry  
**And** for each cached form the cache records only the identifiers needed for the mapping and whether the form has an enabled, valid source link; internal IDs are never exposed by the Public API  
**And** the cache contains no user, session, or visitor identity  
**And** each pod's cache is held in that pod's memory only, with no shared cache, PVC, or external store.

## AC16 - The cache is loaded at start-up, and a load failure does not affect the application

**Given** a Staff or Public backend pod starts  
**When** it loads its valid-form cache  
**Then** a successful load makes the cache available for signal validation  
**And** if the load fails, it is logged to container standard output with a server-defined reason code and no visitor identity and starts that pod's consecutive failed-check streak under AC18  
**And** the pod continues to start and serves every other operation normally, without delaying start-up or any user request  
**And** while the cache has never been loaded successfully, detail-view and source-link signals are rejected without a count and without a database read or write, and the user action is unaffected  
**And** the next scheduled change check (AC18) attempts the load again.

## AC17 - A committed form change updates the handling Staff pod immediately

**Given** a Staff user creates, edits, deletes, or performs any workflow action on a form that changes whether the form is valid for a portal or whether it has an enabled, valid source link  
**When** the change is committed  
**Then** the Staff pod that handled the request updates its own valid-form cache immediately  
**And** the cache is updated only after the change is committed, so a failed or rolled-back change never alters the cache  
**And** other Staff pods and every Public pod reflect the change at their next scheduled change check (AC18).

## AC18 - Every pod checks for changes on a configurable interval

**Given** a Staff or Public backend pod is running  
**When** its change-check interval elapses  
**Then** the pod checks whether the set of valid forms or their source-link state has changed, and reloads its cache only when a change is found  
**And** the check detects changes from any cause, including Staff edits on other pods, workflow and visibility changes, and changes made outside the application  
**And** the interval is set separately for the Staff and Public portals, each by its own environment variable, in minutes  
**And** when that environment variable is blank, not set, or invalid (for example text, zero, or a negative number), the interval is 5 minutes  
**And** if a check fails, the pod uses its last successfully loaded cache indefinitely, logs each failed scheduled check to container standard output without visitor identity, and tries again at the next interval; a pod never loaded successfully continues rejecting signals  
**And** each pod tracks its own consecutive failed startup-load and scheduled change-check attempts, resets the streak after a successful check, and emits one additional stale-cache warning on the twentieth consecutive failure only; the warning states the first failure time and that newly eligible forms may be missing engagement counts on this pod while stale forms may still be counted  
**And** the check performs no forms-table read per signal; its database cost depends only on the interval and the number of pods, not on signal volume.

# Business Rules

- **BR-001:** Detail-view and source-link sources are determined by the portal whose engagement endpoint receives the signal, never by an untrusted caller-supplied label. (Former US-004 BR-003, non-download portion.)
- **BR-002:** Non-download activity counts only through accepted signals whose writer increments complete; accepted signals can be lost after validation under US-007. Raw API reads alone are excluded. Signals are best-effort reports, not verified human actions (Product Owner decision, 2026-10-22).
- **BR-003:** Staff drawer and Public detail-page displays trigger UI detail signals; accepted direct signals can count without a display. Other UI surfaces and raw reads do not themselves send signals (former US-004 BR-005; revised 2026-10-22).
- **BR-004:** The portal attempts a source-link signal when it accepts an enabled action and initiates navigation; the destination need not load and a direct valid signal can count without navigation (former US-004 BR-006; revised 2026-10-22).
- **BR-005:** All otherwise-accepted signals, including identifiable automation and human Staff preview/test activity, receive the same count-write attempt; no bot classification is required (Product Owner decision, 2026-10-22).
- **BR-006:** Detail-view and source-link signals are asynchronous, fire-and-forget, and isolated on one dedicated endpoint per portal. Signal success, rejection, or loss never changes the user action. (Former US-004 BR-013.)
- **BR-007:** Only the Public engagement endpoint has a dedicated edge-native rate-based limit of approximately 100 attempts per minute per trusted client IP, on each edge replica independently, with a bounded documented burst. All attempts, including invalid ones, consume that replica's signal budget; ordinary portal budgets are independent. This is neither a global nor an exact rolling-window ceiling. The Staff endpoint has no per-minute limit; Staff authentication and the analytics database ceiling bound its writes (Product Owner decisions, 2026-10-22; former US-004 BR-014).
- **BR-008:** Signals require a matching `Origin`, or a `Referer` URL whose parsed origin matches when `Origin` is absent. Non-browser clients can forge these headers, so this is best-effort filtering and not proof of human activity (former US-004 BR-015; revised 2026-10-22).
- **BR-009:** Input is validated by allowlist and rejected, never cleaned and accepted. A Staff client supplies the internal form ID; a Public client supplies the existing public form number, resolved to the internal ID by the Public pod's cache without exposing that ID in the Public API. Count, date, source, IP, and portal are server-determined. Numberless legacy Public forms send no signals and have no Public cache entry (Product Owner decisions, 2026-10-22).
- **BR-010:** Each accepted signal results in exactly one US-007 increment request; endpoint database access is parameterized only. (Former US-004 BR-017, endpoint portion.) The engagement endpoints have no database access of their own; their only database work is the US-007 writer's increment, made with the writer's dedicated non-superuser account that can access only the daily-count table, in every environment including local (US-007 AC8 and BR-010, Product Owner confirmed 2026-10-16). Cache loading and change checks (AC16 to AC18) use the portal's existing read access to forms and never use the writer account.
- **BR-011:** Signals are validated against an in-memory valid-form cache in each pod, with no database read per signal (Product Owner decision, 2026-10-16). The signed engagement token proposed earlier the same day is withdrawn.
- **BR-012:** The cache is kept current by start-up load, immediate update on the handling Staff pod after a committed form change, and a change check on every pod at a configurable interval (Product Owner decision, 2026-10-16).
- **BR-013:** The change-check interval is set separately for the Staff and Public portals by one environment variable each, in minutes. A blank, unset, or invalid value means 5 minutes (Product Owner decisions, 2026-10-16).
- **BR-014:** Every failed scheduled startup load or change check is logged to container standard output without visitor identity. Each pod continues using its last good cache indefinitely; until a first successful load, it rejects signals. Each pod resets its consecutive-failure counter on success and emits one additional warning at failure 20 per streak: "Cache checks have failed 20 consecutive times since <first failure time>. Engagement counts for newly eligible forms may be missing on this pod; stale forms may still be counted." The user action is never affected (Product Owner decisions, 2026-10-22).
- **BR-015:** A source-link-click signal is counted only when the cache records an enabled, valid source link for the form; a detail-view signal is counted for any form in the cache.
- **BR-016:** No database rule links daily counts to the forms table; the valid-form cache is the control preventing counts for made-up forms (Product Owner decision, 2026-10-16). Database growth from signals is therefore limited to real forms.

# RBAC / Permissions

## Roles allowed

- Users allowed by existing Staff or Public portal rules to view a form's details or activate its source action may generate qualified detail-view or source-link counts.
- Authenticated Staff sessions may send Staff signals for forms in the Staff valid-form cache.
- Anonymous same-origin Public clients may send Public signals for forms in the Public valid-form cache.

## Roles denied

- A denied or failed underlying UI detail or source action generates no UI signal; this does not prevent an independent valid direct signal from an otherwise authenticated Staff caller from counting.
- Unauthenticated or expired-session callers are denied the Staff engagement endpoint.
- Signals with a missing or mismatched origin are denied at both endpoints.
- Signals for a form not in the receiving pod's valid-form cache, or for a source-link click on a form without an enabled, valid link, are denied at both endpoints.
- Direct callers cannot create qualified non-download counts outside an accepted signal, or change any count's portal source by supplying a portal label.
- No portal role may retrieve aggregate statistics through this story; retrieval is governed by US-010.

## Permission notes

- Signal submission is a consequence of an already authorized or public action and introduces no user-facing event-write permission.
- `form:stats` governs aggregate retrieval only and is not required to generate engagement.
- Staff signals are not checked against the sending user's access to the form. An authenticated Staff user denied a form could send signals for it; this small inflation risk is accepted (Product Owner confirmed, 2026-10-16, after the token was withdrawn).

# Data & Validation Rules

- A signal body contains exactly two values: an internal form ID for Staff or an existing public form number for Public, and a metric that is either detail view or source-link click. Unknown fields are rejected.
- Staff caches hold non-deleted internal form IDs; Public caches map available forms' public numbers to internal IDs, excluding numberless legacy forms. Each entry also records whether it has an enabled, valid source link.
- The Staff and Public change-check intervals are each set by their own environment variable, in minutes (Product Owner confirmed, 2026-10-16). A blank, unset, or invalid value (for example text, zero, or a negative number) means 5 minutes (Product Owner decision, 2026-10-16). Engineering names the variables.
- The signal content type is JSON only. The maximum body size must be the lowest practical size that fits one form identifier and one metric, to keep the endpoints lightweight (Product Owner direction, 2026-10-16). Engineering proposes the exact limit, with options, to the Product Owner for approval.
- Endpoint responses carry no request-supplied value, use a non-HTML content type, and carry the existing `nosniff` protection. Responses are not cacheable.
- Rejection logs contain server-defined reason codes only. Failed scheduled cache-check logs also include the pod's failure streak; the one-time warning at streak 20 includes the timestamp of its first failed check, without request content or visitor identity.

# Edge Cases / Exceptions

- Closing an external destination immediately after navigation starts does not cancel an already counted signal; a lost signal can still leave the navigation uncounted.
- Reopening the same details surface after it was closed is another qualified view; rerendering the same open surface without a new user open action is not.
- Several Public users behind one shared trusted client-IP key share a replica's signal-rate budget; their excess signals are dropped, but ordinary portal use has a separate budget.
- A forged-origin script can still submit counted Public signals for cached forms; separate replica budgets do not enforce a global per-client ceiling.
- An authenticated Staff user or compromised Staff session can inflate Staff counts without a per-minute limit; the analytics database ceiling bounds the load, but not the inflated totals.
- A bot swarm sending made-up form identifiers creates no rows and causes no database work; each signal is rejected in memory. Bots can still inflate counts for real forms, within the Public limit per IP, and the number of rows can grow by at most 6 per real form per day.
- After a form is deleted, unpublished, archived, or made non-public, pods other than the handling Staff pod, and every Public pod, may keep counting it until a successful change check; repeated failures can extend this indefinitely. Counts for deleted forms are retained but never returned (US-010 AC10).
- After a form is created or published, other Staff pods and Public pods may reject its signals until a successful change check; repeated failures can extend this indefinitely. The Public form list also has its independent up-to-five-minute response cache.
- New forms require an approved form-number reservation at creation under US-012; existing numberless Draft, Pending Review, Archived, and Published forms retain existing workflow and publication behavior. A numberless Public form cannot send a Public engagement signal under this feature; no form-number assignment on Edit or new publication check is introduced.
- If a pod's start-up load fails and every later check also fails, that pod counts no detail or link activity while every other function works normally; the failures appear only in standard-output logs. Requests reaching other pods are counted normally.
- If a change check fails after a successful load, the pod keeps using its last good cache, so deleted forms may stay counted and new forms stay uncounted on that pod until a check succeeds.
- A pod restart empties its cache until the start-up load completes; signals reaching that pod in that time are rejected.

# Audit / Business Events

- Engagement counts are aggregate analytics data and do not appear in the user-facing form audit history.
- Rejected, rate-limited, or denied signals do not appear in that history.
- Existing security logging for denied access remains unchanged.

# Outstanding Questions

- Engineering handoff note: the Public NGINX edge currently rejects every non-GET method server-wide, so the endpoint needs a POST exception limited to its exact path, with its own `limit_req` zone. No Staff rate limiter is required.
- Staff Coraza WAF coverage must continue to apply to the Staff endpoint; it is not exempted.
- Engineering handoff note: change detection must detect source-link, visibility, deletion, and out-of-application changes even when a form count or latest-change timestamp alone would stay unchanged. Propose and verify a reliable check without forms-table reads per signal. PgBouncer transaction pooling prevents relying on database change notifications; Public pods read through the existing Public forms view.
- Engineering handoff note: the two interval environment variables are added to the Staff and Public backend Helm values with the 5-minute default.
- Engineering handoff note: propose the maximum signal body size to the Product Owner as options, each the lowest practical size for one form identifier and one metric, applied at the Public NGINX edge and in the Staff and Public backends.
