---
feature_id: FEAT-0031
story_id: US-009
test_id: TC-009
owner: Quality Analyst
status: draft
created: 2026-10-16 13:30:00
updated: 2026-10-22
depends_on: [US-007, US-008, US-011]
---

# Traceability

| Acceptance Criterion | Test Coverage |
|---|---|
| AC1 | TC 9.1, TC 9.2, TC 9.22 |
| AC2 | TC 9.3, TC 9.4 |
| AC3 | TC 9.5 |
| AC4 | TC 9.6 |
| AC5 | TC 9.7 |
| AC6 | TC 9.8 |
| AC7 | TC 9.9 |
| AC8 | TC 9.10, TC 9.11 |
| AC9 | TC 9.12, TC 9.13, TC 9.14, TC 9.34 |
| AC10 | TC 9.15 |
| AC11 | TC 9.16, TC 9.17, TC 9.33 |
| AC12 | TC 9.18, TC 9.19, TC 9.23, TC 9.33 |
| AC13 | TC 9.20 |
| AC14 | TC 9.21 |
| AC15 | TC 9.22, TC 9.24, TC 9.33 |
| AC16 | TC 9.25, TC 9.26 |
| AC17 | TC 9.27, TC 9.28 |
| AC18 | TC 9.29, TC 9.30, TC 9.31, TC 9.32 |

Legacy mapping: TC 4.3, TC 4.4, TC 4.5, TC 4.6, TC 4.18 through TC 4.27, TC 4.29, and the non-download portions of TC 4.7, TC 4.8, TC 4.9, TC 4.10, TC 4.11, and TC 4.12 from the former TC-US-004. TC 9.22 through TC 9.32 are new for the valid-form cache (Product Owner decisions, 2026-10-16). They replace the withdrawn engagement-token tests that briefly used the same numbers.

# Test Cases

All portal-action cases use Playwright against the Product Owner-deployed local Staff and Public portals in the shared integrated browser. Use Playwright `APIRequestContext` for direct and modified-request cases, through the Public edge when checking its limiter. Each case uses isolated daily counts. Rate-limit cases run only in local or TEST. Unless a case states otherwise, Staff signals use internal form IDs and Public signals use public form numbers already present in the receiving pod's valid-form cache. Cache cases that depend on pod count or start-up run in TEST, or in local with the stated replica count, and control scheduled checks through test-only support.

## TC 9.1 - Enabled Staff and Public source actions increment daily counts

**Covers:** AC1  
**Supersedes:** TC 4.3  
**Type:** Positive, parameterized Playwright UI

**Preconditions**

- A form has a valid enabled external source URL exposed in Staff and Public portal surfaces.

**Steps**

1. Activate the source action through each portal in isolated contexts and observe one attempted UI signal per activation.
2. Confirm portal navigation initiation without asserting external load completion.
3. Close the external destination immediately after navigation starts.
4. Inspect the daily source-link-click counts.

**Expected outcome**

- With no signal loss or writer fault induced, each accepted signal increases its correct form, PCT day, and receiving source count by one, including when the destination is closed immediately. Destination load is not asserted.

## TC 9.2 - Non-portal and unusable URL behavior is excluded

**Covers:** AC1  
**Supersedes:** TC 4.4  
**Type:** Negative, parameterized Playwright UI and APIRequestContext

**Preconditions**

- Each variant below is available in isolation: copied URL navigation; direct browser navigation to the URL; form with no URL; form with an invalid URL; disabled source action; direct API request that is not an engagement signal.

**Steps**

1. Exercise one variant per isolated case.
2. Inspect daily source-link-click counts.

**Expected outcome**

- No variant increases a source-link-click count.

## TC 9.3 - Staff drawer and Public detail page displays count

**Covers:** AC2  
**Supersedes:** TC 4.5  
**Type:** Positive, parameterized Playwright UI

**Preconditions**

- A form is visible in the Staff drawer and Public detail page.

**Steps**

1. Successfully open and display the Staff drawer and observe its attempted signal.
2. Successfully open and display the Public detail page in isolation and observe its attempted signal carrying the public form number.
3. Inspect daily detail-view counts.

**Expected outcome**

- With no signal loss or writer fault induced, each accepted signal increases its correct form, PCT day, and receiving source count by one; the UI never sends the internal UUID from the Public portal.

## TC 9.4 - Excluded surfaces and failed displays do not count

**Covers:** AC2  
**Supersedes:** TC 4.6  
**Type:** Negative, parameterized Playwright UI and APIRequestContext

**Preconditions**

- Each variant below is available in isolation: Add New Form; Edit Form; form card; raw detail API read; preview; Form Insights display; failed Staff drawer display; failed Public detail-page display.

**Steps**

1. Exercise one variant per isolated case.
2. Inspect daily detail-view counts.

**Expected outcome**

- No variant increases a detail-view count.

## TC 9.5 - Repeated detail and link actions count; rerender does not

**Covers:** AC3  
**Supersedes:** TC 4.7 (detail and link portion)  
**Type:** Positive and negative repeat behavior, Playwright UI

**Preconditions**

- One user/session can repeat detail views and source-link activations.
- An open detail surface can be rerendered without a new user open action, for example by a data refresh.

**Steps**

1. Open, close, and reopen the same detail surface three times, and activate the same source link three times, in one session.
2. Repeat one of each action in a second session for the same form and source.
3. With a detail surface open, trigger a rerender without a new open action.
4. Inspect daily counts.

**Expected outcome**

- Detail-view and source-link counts each increase by four; no user or session deduplication occurs.
- The rerender in step 3 adds no count.

## TC 9.6 - Direct and cross-labelled non-download requests do not count or relabel

**Covers:** AC4  
**Supersedes:** TC 4.8 (non-download portion)  
**Type:** Security and negative attribution, parameterized Playwright APIRequestContext

**Preconditions**

- Raw detail API reads and otherwise-valid signals carrying an extra field with the other portal's label are available.

**Steps**

1. Send raw detail API reads directly.
2. Send otherwise-valid signals to each endpoint carrying an extra portal-label field naming the other portal.
3. Inspect daily counts for both sources.

**Expected outcome**

- Raw reads increase no count.
- Cross-labelled signals are rejected under AC11 as having an extra field, and no count changes for either source.

## TC 9.7 - All otherwise-accepted signals count regardless of automation

**Covers:** AC5  
**Supersedes:** TC 4.9 (detail and link portion)  
**Type:** Positive traffic classification, parameterized Playwright UI and APIRequestContext

**Preconditions**

- Human Staff preview/test and Public UI actions can be performed, and identifiable automated clients can send otherwise-valid direct signals. All test forms are in the corresponding caches.

**Steps**

1. Perform one detail view and one source-link activation through each UI and observe attempted signals.
2. Submit one otherwise-valid direct signal per metric and portal from each identifiable automated traffic class; inspect counts.

**Expected outcome**

- Every accepted, successfully written signal increases its metric's receiving-portal count by one regardless of automation label; no bot classification rejects an otherwise-valid signal.
- A crawler routed to server-rendered metadata sends no UI signal merely by reading that page, but a valid direct signal from the same automation counts.

## TC 9.8 - Denied UI actions send no signal; direct Staff signals remain best effort

**Covers:** AC6  
**Supersedes:** TC 4.12 (detail and link portion)  
**Type:** Negative RBAC and visibility, parameterized Playwright UI and APIRequestContext

**Preconditions**

- Users and forms cover denied Staff detail, denied source action, and a form unavailable to the Public portal.

**Steps**

1. Attempt each denied underlying action through UI and the existing detail or source API in isolation, and observe signal requests.
2. Separately send an otherwise-valid Staff engagement signal as an authenticated user denied access to that cached form; send a Public signal for a form absent from the Public cache.
3. Inspect denials and daily counts.

**Expected outcome**

- Existing underlying action denials remain, and no denied UI action sends a signal or increases a count by itself.
- The authenticated direct Staff signal is accepted and counts despite that sender's underlying form denial; the unavailable Public form signal is rejected without a count.

## TC 9.9 - Count failure does not block detail display or navigation

**Covers:** AC7  
**Supersedes:** TC 4.10 (detail and link portion)  
**Type:** Exception, parameterized Playwright end-to-end

**Preconditions**

- Count increment failure can be induced for detail views and source links on each source.

**Steps**

1. For each metric and source in isolation, perform an otherwise-successful action while its increment fails.
2. Inspect the user-visible result, notifications, and daily count.

**Expected outcome**

- The detail display or navigation succeeds, with no telemetry-failure notification.
- With a test-only pre-write drop, no count increases; an induced timeout with an uncertain outcome is covered separately by TC 7.6.

## TC 9.10 - UI actions do not wait for the signal

**Covers:** AC8  
**Supersedes:** TC 4.18  
**Type:** Positive and non-blocking behavior, Playwright UI

**Preconditions**

- Playwright route interception can delay or fail each portal's engagement endpoint response.

**Steps**

1. With endpoint responses delayed by 10 seconds, open a Staff drawer, a Public detail page, and activate a source link in each portal; include immediate external navigation.
2. Repeat with the endpoint returning a server error.

**Expected outcome**

- Each detail display and navigation start completes without waiting for the endpoint response.
- Exactly one signal is attempted per qualified UI action without waiting for its result, including navigation; a lost signal need not change a count, and no user-visible notification appears.

## TC 9.11 - Endpoint rejects download and unknown metrics

**Covers:** AC8  
**Supersedes:** TC 4.19  
**Type:** Negative, parameterized Playwright APIRequestContext

**Preconditions**

- A visible form and valid same-origin request headers for each portal endpoint.

**Steps**

1. Send otherwise-valid signals whose metric is download, then an unknown metric value, each in isolation.
2. Inspect responses and daily counts.

**Expected outcome**

- Both signals are rejected; no download, detail-view, or source-link count changes.

## TC 9.12 - Every Public signal attempt consumes a separate per-replica rate budget

**Covers:** AC9  
**Supersedes:** TC 4.20  
**Type:** Boundary and DoS resilience, Playwright APIRequestContext

**Preconditions**

- One trusted client-IP key, one controlled Public edge replica, and an isolated count. Its configured approximately 100-attempts-per-minute rate and finite burst are documented; analytics statement activity can be observed.

**Steps**

1. Send valid signals at a pace within the configured edge rate and burst through that replica and record responses and completed writes.
2. Send malformed and valid attempts above its configured rate and burst through the same edge, recording each rejection.
3. Send an otherwise-valid signal while its budget is exhausted and compare count and database activity; after the limiter recovers, send another valid signal.

**Expected outcome**

- Both malformed and valid requests consume the dedicated edge budget; excess attempts are rate-limited before signal validation or analytics database work, while the separate ordinary API budget is unaffected.
- The count increases only for accepted signals whose writer increments complete; no exact rolling-window total or guarantee that the first 100 rapid requests succeed is asserted. A later within-rate accepted signal can count.

## TC 9.13 - Public signal flood does not block ordinary access

**Covers:** AC9  
**Supersedes:** TC 4.21  
**Type:** Isolation, Playwright UI and APIRequestContext

**Preconditions**

- One client address can send signals and use the Public portal.

**Steps**

1. Exhaust one replica's dedicated signal-rate burst for that trusted client-IP key using valid and malformed attempts.
2. Within the same minute, load the Public forms list, open a detail page, and download a file.

**Expected outcome**

- Ordinary portal requests succeed and are not rate-limited because of signal volume.
- The detail display succeeds with no notification while its own signal is rejected; the download is counted through its handoff under US-008.

## TC 9.14 - Staff endpoint has no per-minute limit

**Covers:** AC9  
**Supersedes:** TC 4.29  
**Type:** Boundary, Playwright APIRequestContext

**Preconditions**

- One authenticated Staff session from one client address; analytics write ceiling set high enough not to drop signals.

**Steps**

1. Send 120 valid Staff signals within one minute at a steady rate.
2. Inspect responses and the Staff daily count.

**Expected outcome**

- No signal is rejected as rate-limited; the Staff count increases by 120.

## TC 9.15 - Missing or mismatched origin is rejected

**Covers:** AC10  
**Supersedes:** TC 4.22  
**Type:** Security allow and deny, parameterized Playwright APIRequestContext

**Preconditions**

- Valid signal bodies for each portal endpoint.

**Steps**

1. Send a signal with each header case in isolation: matching `Origin`; no `Origin` with a full `Referer` URL whose parsed scheme, host, and port match; other-portal origin; external origin; scheme or port mismatch; `null` origin; matching `Referer` with mismatched `Origin`; neither header.
2. Inspect responses and daily counts.

**Expected outcome**

- Only the matching-`Origin` case and the matching-`Referer`-without-`Origin` case are accepted and counted once each.
- Every other case is rejected with no count change.

## TC 9.16 - Malformed and malicious bodies are rejected

**Covers:** AC11  
**Supersedes:** TC 4.23  
**Type:** Security negative, parameterized Playwright APIRequestContext

**Preconditions**

- Valid origin headers; known starting counts.

**Steps**

1. Send in isolation: script and HTML markup in each field; SQL fragments such as quote, comment, `UNION`, and stacked-statement payloads; control and Unicode direction characters; extra fields; a form identifier not in the application's identifier format; caller-supplied count, date, source, IP, and portal fields; non-JSON content type; malformed JSON; oversized body; empty body; wrong value types.
2. Inspect responses, daily counts, analytics table row set, database statement activity, and new log output.

**Expected outcome**

- Every case is rejected; no count or row is created or changed, and no database read or write occurs.
- No database error detail is returned; logs contain reason codes only.

## TC 9.17 - Responses never reflect request content

**Covers:** AC11  
**Supersedes:** TC 4.24  
**Type:** XSS prevention, parameterized Playwright APIRequestContext and UI

**Preconditions**

- Marker payloads containing unique script and markup strings.
- An authorized statistics user can open Form Insights (US-011).

**Steps**

1. Send rejected bodies containing the marker in each forbidden field; separately send valid accepted bodies with the marker in an untrusted optional request header that must not be reflected.
2. Inspect each response body, content type, `X-Content-Type-Options`, and cache headers.
3. Open the form's statistics in Form Insights after accepted signals.

**Expected outcome**

- No response contains the marker; responses use a non-HTML content type with `nosniff` and are not cacheable.
- Statistics show only numeric counts; no marker or script executes.

## TC 9.18 - Made-up, deleted, and unavailable forms are rejected in memory

**Covers:** AC12  
**Supersedes:** TC 4.25 (revised 2026-10-16 for the valid-form cache)  
**Type:** Data integrity negative, parameterized Playwright APIRequestContext

**Preconditions**

- Variants: a well-formed identifier that has never existed; a form deleted before the pods' caches were last loaded; a form not available to the Public portal when its caches were last loaded.
- The analytics table row set is recorded; database statement activity can be observed in TEST.

**Steps**

1. In isolation, send a well-formed Staff internal ID or Public form number, as applicable, for each variant to each endpoint.
2. Compare the analytics row set and counts with the starting state, and inspect database statement activity.

**Expected outcome**

- Every signal is rejected.
- No row is created, no count changes, and no database read or write occurs for any variant.

## TC 9.19 - A successfully written signal changes exactly one count by one

**Covers:** AC12  
**Supersedes:** TC 4.26  
**Type:** Data integrity positive, Playwright APIRequestContext

**Preconditions**

- A visible numbered Public form with known daily counts for all metrics and sources; the full analytics row set is recorded and the writer is below its ceiling without faults.

**Steps**

1. Send one valid Public detail-view signal.
2. Compare the full analytics row set with the starting state.
3. Attempt read, decrement, reset, and delete operations against the endpoint.

**Expected outcome**

- Only the cached internal ID's Public detail-view count for today's PCT day increases by one; every other row is unchanged and the internal ID is absent from the Public response.
- Every step 3 attempt is rejected; the endpoint offers no operation that reads other data, decrements, resets, or deletes counts.

## TC 9.20 - Staff endpoint requires authentication

**Covers:** AC13  
**Supersedes:** TC 4.27  
**Type:** RBAC allow and deny, Playwright APIRequestContext

**Preconditions**

- A valid Staff session, an expired session, and no session; a Public client with no session.

**Steps**

1. Send a valid Staff signal with each Staff session state, each in isolation.
2. Send a valid Public signal with no session.

**Expected outcome**

- The valid Staff session is counted once; expired and missing sessions are rejected without counts.
- The unauthenticated Public signal is counted once.

## TC 9.21 - New signal output contains no visitor identity

**Covers:** AC14  
**Supersedes:** TC 4.11 (signal-output portion)  
**Type:** Privacy contract, Playwright APIRequestContext and log inspection

**Preconditions**

- Authenticated Staff and anonymous Public signals have been accepted, rejected for validation, and rejected for rate limit.

**Steps**

1. Inspect new engagement-endpoint log output and responses for each outcome.
2. Search for names, emails, account IDs, IP addresses, user agents, screen resolution, and request identity fields.

**Expected outcome**

- No visitor identity field or value appears in new signal logs or responses.
- Rejection logs contain only server-defined reason codes.

## TC 9.22 - Each portal's cache holds the right forms and link state

**Covers:** AC1, AC15  
**Type:** Positive and negative, parameterized Playwright APIRequestContext

**Preconditions**

- Numbered forms loaded into the caches: a Public published form with an enabled valid source link; a Public published form with no source link; a form with a disabled source link; a form with an invalid source link; a Staff-only non-deleted form with an enabled valid source link.

**Steps**

1. For each form in isolation, send detail-view and source-link signals using its internal ID at the Staff endpoint, then its public number (if publicly available) at the Public endpoint.
2. Inspect responses and daily counts.

**Expected outcome**

- Staff detail-view signals are counted for every cached form; Public detail-view signals count only for numbered Public forms.
- Staff source-link signals count for both forms with enabled valid links, including the Staff-only form. Public link signals count only when both the Public number is cached and its link is enabled and valid; other link signals are rejected.

## TC 9.23 - No forms-table read occurs per signal, and bots cannot grow the database with made-up forms

**Covers:** AC12  
**Type:** Performance and DoS resilience, Playwright APIRequestContext

**Preconditions**

- In TEST, database statement activity can be observed per table; the analytics table row count is recorded.

**Steps**

1. Send 50 valid signals across both endpoints and both metrics below the configured edge and writer ceilings.
2. Through controlled clients below their respective edge-replica signal budgets, send 500 signals with distinct, well-formed, made-up Staff IDs or Public form numbers.
3. Inspect database statement activity and the analytics row count.

**Expected outcome**

- The only database statements caused by step 1 are the 50 completed count increments; no statement reads the forms table or any other table to validate a signal.
- Step 2 causes no database statement and no new row.

## TC 9.24 - The cache contains no identity and is held only in pod memory

**Covers:** AC15  
**Type:** Privacy and design contract, Playwright APIRequestContext with protected test support in TEST

**Preconditions**

- Protected test support can report a pod's cache contents and size.

**Steps**

1. Inspect the cache contents on one Staff and one Public pod.
2. Confirm no PVC, Redis, or other shared store is used for the cache.

**Expected outcome**

- Each entry contains only a form identifier and its source-link state; no user, session, or visitor value is present.
- The cache exists only in each pod's memory.

## TC 9.25 - Cache is loaded at start-up

**Covers:** AC16  
**Type:** Positive, Playwright APIRequestContext

**Preconditions**

- A known form is in the database; one Staff and one Public backend pod can be restarted.

**Steps**

1. Restart each pod and wait until it is ready and has completed its first successful cache load.
2. Send a detail-view signal using the internal ID on Staff and the public number on Public.
3. Inspect daily counts.

**Expected outcome**

- Each signal is counted once under its own portal.

## TC 9.26 - Start-up load failure is logged and the application keeps working

**Covers:** AC16  
**Type:** Exception, Playwright UI and APIRequestContext in local or TEST

**Preconditions**

- A test-only fault makes the cache load fail on start-up for one Staff pod and one Public pod, each running as the only replica in its portal; the change-check interval is set to 1 minute.

**Steps**

1. Start each pod with the fault active.
2. Without waiting, use each portal: load the forms list, open a form's detail, follow a source link, and download a file.
3. Send detail-view and source-link signals to each endpoint and inspect daily counts and database activity.
4. Inspect container standard output.
5. Remove the fault, wait for one change-check interval, then send one detail-view signal to each endpoint.

**Expected outcome**

- Each pod starts and becomes ready with no delay from the failed load; every step 2 action succeeds with no user-visible error or notification.
- Step 3 signals are rejected without a count and without database work.
- Standard output contains one cache-load failure entry per pod with a reason code and no visitor identity.
- Step 5 signals are counted once each, and each pod's consecutive-failure streak is reset after its successful check.

## TC 9.27 - The handling Staff pod updates its cache immediately after a committed change

**Covers:** AC17  
**Type:** Positive, parameterized Playwright UI and APIRequestContext

**Preconditions**

- One Staff backend replica; the Staff change-check interval is set to 60 minutes so only the immediate update can take effect during the test.
- Variants: create a form using an approved unused number under US-012; delete a form; disable a form's source link; enable a valid source link; a workflow action that changes the form's validity.

**Steps**

1. For each variant in isolation, perform the change through the Staff UI and wait for it to save.
2. Immediately send detail-view and source-link-click signals for the affected form to the Staff endpoint.
3. Inspect daily counts.

**Expected outcome**

- Each signal reflects the change at once: new forms and newly enabled links are counted; deleted forms and disabled links are rejected without a count.

## TC 9.28 - A failed or rolled-back change never alters the cache

**Covers:** AC17  
**Type:** Negative, Playwright UI and APIRequestContext

**Preconditions**

- One Staff backend replica with a 60-minute change-check interval; a test-only fault makes a form delete fail and roll back.

**Steps**

1. Attempt to delete the form with the fault active and confirm the delete fails.
2. Send a detail-view signal for that form to the Staff endpoint.
3. Inspect daily counts.

**Expected outcome**

- The signal is counted, because the form remains valid and the cache was not changed.

## TC 9.29 - Other pods and Public reflect changes at the next change check

**Covers:** AC18  
**Type:** Boundary, Playwright APIRequestContext in TEST

**Preconditions**

- Two Staff replicas and one Public replica; each portal's interval is set to 2 minutes; signals can be directed to a specific pod.

**Steps**

1. Through Staff pod A, publish a new Public form and delete another form.
2. Before 2 minutes have passed, send signals for both forms to Staff pod B and to the Public pod.
3. After protected test support observes a successful scheduled check on each remaining pod, send the same signals again.
4. Inspect daily counts.

**Expected outcome**

- In step 2, pod B and the Public pod may still reflect the old state, with each outcome consistent with its last check.
- In step 3, the new form is counted and the deleted form is rejected on every pod.

## TC 9.30 - Changes made outside the application are detected

**Covers:** AC18  
**Type:** Boundary, Playwright APIRequestContext in local or TEST

**Preconditions**

- One Staff and one Public replica with 1-minute intervals; protected test support can change forms data directly in the database.

**Steps**

1. Directly in the database, make one form non-public, soft-delete another, and change an older form's enabled source link without changing the total number of forms or the latest unrelated form's change time.
2. Wait for protected test support to observe each pod's next successful check and send applicable signals for all changed forms.
3. Inspect daily counts.

**Expected outcome**

- The non-public form is rejected on Public and still counted on Staff; the deleted form is rejected on both; link-signal eligibility reflects the changed older form. Detection cannot rely solely on form count plus maximum change time.

## TC 9.31 - Interval is set per portal, defaulting to 5 minutes

**Covers:** AC18  
**Type:** Configuration boundary, Playwright APIRequestContext in local or TEST

**Preconditions**

- Server time can be advanced deterministically; protected test support can report each pod's last change-check time.

**Steps**

1. Set the Staff variable to 2 minutes and the Public variable to 7 minutes; record each pod's check times over 15 minutes.
2. Set both variables blank, restart, and record check times over 15 minutes.
3. Remove both variables, restart, and record check times over 15 minutes.
4. In isolation, set both variables to each invalid value: text, zero, and a negative number; restart and record check times over 15 minutes.

**Expected outcome**

- In step 1, Staff checks every 2 minutes and Public every 7 minutes, independently.
- In steps 2, 3, and 4, both portals check every 5 minutes, and each pod starts and serves normally.

## TC 9.32 - Failed checks retain the last cache and warn once at failure 20

**Covers:** AC18  
**Type:** Exception, Playwright APIRequestContext in local or TEST

**Preconditions**

- One Staff and one Public replica with 1-minute intervals, each with a successfully loaded cache; protected test support can advance scheduled check time and observe per-pod failure streaks; a test-only fault makes checks fail.

**Steps**

1. Activate the fault and cause 19 consecutive failed checks on each pod. Send one valid signal for a last-good cached form and one for a newly eligible form absent from that cache; inspect stdout.
2. Cause the twentieth and twenty-first failed checks; inspect per-pod failure logs, warning count, its first-failure timestamp, and signal outcomes.
3. Remove the fault and observe one successful check per pod; cause a new streak of 20 failed checks and inspect stdout again.

**Expected outcome**

- Each cached-form signal can count throughout repeated failures; a newly eligible form absent from the cache is rejected. The last good cache never expires solely because of age; normal user actions are unaffected.
- Each pod writes one identity-free failure entry per failed scheduled check. It writes no stale-cache warning at failure 19, exactly one additional warning at failure 20, and no second warning at failure 21; that warning identifies the first failed-check time and says newly eligible forms may be missing counts on this pod while stale forms may still be counted.
- A successful check resets only that pod's streak; another warning is emitted once at failure 20 in its next streak.

## TC 9.33 - Public form numbers resolve without exposing internal IDs

**Covers:** AC11, AC12, AC15  
**Type:** Positive and negative mapping, Playwright Public UI and APIRequestContext

**Preconditions**

- A numbered Public form and a grandfathered numberless Published Public form are available under existing Public rules; the Public pod has loaded its cache.

**Steps**

1. Display the numbered form and capture its Public detail payload and outgoing UI signal.
2. Submit an otherwise-valid direct Public signal with its number, then one with its internal UUID, a made-up number, and no number, each in isolation.
3. Inspect Public cache keys and target daily counts; inspect the numberless form through its existing Public surface.

**Expected outcome**

- Public payloads and signals expose only the public number, never the internal UUID; the valid number maps to the correct internal form's count.
- The internal UUID, made-up number, and missing number are rejected without writer or forms-table work. The numberless legacy form retains its current Public availability but has no Public signal-cache entry or qualified Public UI signal.

## TC 9.34 - Public edge replicas use separate trusted-IP signal budgets

**Covers:** AC9  
**Type:** Edge configuration and security boundary, Playwright APIRequestContext in TEST

**Preconditions**

- Two controlled Public edge replicas with documented rate and burst settings; trusted proxy client-IP handling can be observed and a test client can supply an untrusted conflicting forwarding header.

**Steps**

1. Exhaust one replica's dedicated signal budget from one trusted client-IP key with valid and malformed attempts.
2. Send a request under the same trusted key through the other replica, then try to reset the first budget using an untrusted client-supplied IP header.
3. Send an ordinary Public form request through each replica and inspect outcomes and analytics writes.

**Expected outcome**

- The first replica rate-limits its excess signal attempts without database work; the other replica has its own budget. No deployment-wide hard 100-per-minute guarantee is claimed.
- An untrusted IP header cannot select a different limiter key; ordinary Public requests remain subject only to their independent limits.

# Test Data Notes

- Use one known form per metric/source combination to avoid ambiguous totals.
- Use external test URLs controlled by the test environment.
- Identifiable automation is not excluded when it submits an otherwise-valid signal; a crawler that receives only server-rendered metadata sends no UI signal by that route.
- Run rate-limit cases only in local or TEST environments, never against PROD.
- Malicious payloads are inert test strings; do not use payloads that target systems outside the test environment.
- Cache tests set the change-check interval through each portal's environment variable and use test-only fault controls available in local or TEST only.

# Regression Notes

- Re-run Staff drawer, Public detail, and external-link coverage.
- Verify telemetry does not delay or block ordinary portal actions.
- Re-run existing Public rate-limit, method allow-list, and security-header coverage; the POST exception must not open POST on any other Public path.
- Re-run Staff Coraza WAF coverage and confirm the new endpoint is not exempted from it.
- Re-run Public form list cache coverage and confirm its up-to-5-minute behavior is unchanged.
- Re-run Staff form create, edit, delete, and workflow suites; each now also updates the handling pod's valid-form cache after commit.
- Re-run Staff and Public backend start-up and readiness checks; a cache load failure must not delay readiness.
