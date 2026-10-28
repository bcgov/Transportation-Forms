---
feature_id: FEAT-0031
story_id: US-008
test_id: TC-008
owner: Quality Analyst
status: draft
created: 2026-10-16 13:30:00
updated: 2026-10-22
depends_on: [US-007]
---

# Traceability

| Acceptance Criterion | Test Coverage |
|---|---|
| AC1 | TC 8.1, TC 8.2, TC 8.3, TC 8.8, TC 8.12 |
| AC2 | TC 8.4, TC 8.12 |
| AC3 | TC 8.5 |
| AC4 | TC 8.6 |
| AC5 | TC 8.7 |
| AC6 | TC 8.8, TC 8.9 |
| AC7 | TC 8.10 |
| AC8 | TC 8.11 |
| AC9 | TC 8.1 |

Legacy mapping: TC 4.1, TC 4.2, TC 4.15, TC 4.16, TC 4.17, and the download portions of TC 4.7, TC 4.8, TC 4.9, TC 4.10, TC 4.11, and TC 4.12 from the former TC-US-004.

# Test Cases

All portal-action cases use Playwright against the Product Owner-deployed local Staff and Public portals in the shared integrated browser. Use Playwright `APIRequestContext` for direct and modified-request cases. Each case uses isolated daily counts.

## TC 8.1 - Successful Staff and Public downloads increment daily counts

**Covers:** AC1, AC9  
**Supersedes:** TC 4.1  
**Type:** Positive, parameterized Playwright end-to-end

**Preconditions**

- A visible form has a downloadable attachment in both allowed Staff and Public contexts.
- Engagement-endpoint requests can be observed.

**Steps**

1. Download through the Staff portal and wait for the successful file response.
2. Download through the Public portal in an isolated context.
3. Inspect observed network requests and query the daily counts through protected test support.

**Expected outcome**

- Each action increases only its form, download metric, PCT day, and serving portal count by one.
- No engagement-endpoint signal is sent for either download.

## TC 8.2 - Pre-handoff failures do not count

**Covers:** AC1  
**Supersedes:** TC 4.2  
**Type:** Negative and exception, parameterized Playwright UI and APIRequestContext

**Preconditions**

- A file-response failure before handoff can be induced through UI and through a direct API request.

**Steps**

1. For each request mode in isolation, attempt a download whose file response fails before successful handoff.
2. Inspect the daily download counts.

**Expected outcome**

- No download count increases for the failed request.

## TC 8.3 - Post-handoff transfer failures do not reverse a count

**Covers:** AC1  
**Supersedes:** TC 4.15  
**Type:** Interrupted transfer, Playwright end-to-end

**Preconditions**

- An authorized Staff file response can be handed off after opening the stream and then fail on a later chunk; a Public API can return `X-Accel-Redirect` before the edge fetch fails; either transfer can also be interrupted by the client.
- The starting daily count for the form, source, and PCT day is known.

**Steps**

1. In isolation, induce a later Staff streaming failure, a later Public edge/storage fetch failure, and a client disconnect after the respective API's successful handoff.
2. Inspect each serving API handoff and its daily count after the downstream failure.

**Expected outcome**

- Each authorized API handoff is counted once, even when the subsequent transfer or edge fetch fails.
- The download is not counted a second time when transfer termination is observed.

## TC 8.4 - Repeated downloads are counted without deduplication

**Covers:** AC2  
**Supersedes:** TC 4.7 (download portion)  
**Type:** Positive repeat behavior, Playwright UI

**Preconditions**

- One user/session can repeat a download of the same attachment.

**Steps**

1. Download the same attachment three times in the same session.
2. Repeat once in a second session for the same form and source.
3. Inspect the daily download count.

**Expected outcome**

- The count increases by four; no user or session deduplication occurs.

## TC 8.5 - Direct downloads use the serving API as source

**Covers:** AC3  
**Supersedes:** TC 4.8 (download portion)  
**Type:** Security and negative attribution, parameterized Playwright APIRequestContext

**Preconditions**

- Allowed direct requests to each file API can carry a conflicting caller-supplied portal label.

**Steps**

1. For each file API in isolation, produce an allowed direct download carrying the other portal's label.
2. Inspect daily download counts for both sources.

**Expected outcome**

- Each direct download increments only the serving Staff or Public file API source, not the caller's label.

## TC 8.6 - Identifiable bot downloads are counted

**Covers:** AC4  
**Supersedes:** TC 4.9 (download portion)  
**Type:** Positive traffic classification, parameterized Playwright APIRequestContext

**Preconditions**

- Identifiable health-check, bot, and automated-test traffic can be marked deterministically for each file API.

**Steps**

1. For each traffic class and file API in isolation, perform a successful authorized download.
2. Inspect daily download counts.

**Expected outcome**

- Each successful authorized download increases the serving source's download count by one, regardless of bot classification.

## TC 8.7 - Denied downloads create no count

**Covers:** AC5  
**Supersedes:** TC 4.12 (download portion)  
**Type:** Negative RBAC and visibility, parameterized Playwright UI and APIRequestContext

**Preconditions**

- Users and forms cover a denied Staff attachment and an attachment on a form unavailable to the Public portal.

**Steps**

1. For each case, attempt the download through UI and directly, each in isolation.
2. Inspect denial responses and daily counts.

**Expected outcome**

- Existing denials remain in effect.
- No download count increases.

## TC 8.8 - Direct and UI handoffs retain existing audits without new analytics rows

**Covers:** AC1, AC6  
**Supersedes:** TC 4.16  
**Type:** Positive, parameterized Playwright UI and APIRequestContext

**Preconditions**

- Successful Staff and Public file requests can be made through UI and directly, including an identifiable bot request.
- The authorized file name and serving API are known; existing Staff and Public audits, container standard output, and daily counts can be inspected against pre-feature behavior.

**Steps**

1. Make one successful authorized file request for each source and request mode in an isolated test case.
2. Inspect the serving source's download count, existing download audit output, new analytics stdout output, and analytics database.

**Expected outcome**

- Each successful handoff increases its serving source's daily download count by one, including direct API and identifiable-bot requests.
- Existing Staff and Public download audits retain their pre-feature behavior; no additional per-download analytics stdout record appears.
- No per-download analytics row is stored in the database.

## TC 8.9 - Denied and pre-handoff failed requests do not count

**Covers:** AC6  
**Supersedes:** TC 4.17  
**Type:** Negative, parameterized Playwright APIRequestContext

**Preconditions**

- A denied file request and a pre-handoff failure can each be induced in isolation; their existing audit behavior can be compared with the pre-feature baseline.

**Steps**

1. Attempt each denied or pre-handoff failed file request in an isolated case.
2. Inspect the response, daily count, and existing audits.

**Expected outcome**

- The request remains denied or fails under the existing file-access rule.
- No download count increases; existing denied/failed-request audit behavior is unchanged and no new analytics stdout record is emitted.

## TC 8.10 - New download analytics contains no visitor identity

**Covers:** AC7  
**Supersedes:** TC 4.11 (download-record portion)  
**Type:** Privacy contract, Playwright APIRequestContext and log inspection

**Preconditions**

- An authenticated Staff download and an anonymous Public download have each produced their existing audit output and daily count; new analytics data and summaries can be inspected.

**Steps**

1. Inspect the daily-count row and any new analytics failure summaries for visitor-identity fields.
2. Compare existing Staff audit rows and Public download audit logs with their pre-feature behavior.
3. Inspect stdout for any additional per-download analytics record.

**Expected outcome**

- New analytics count rows and summaries contain no visitor identity, IP, user agent, or individual download record.
- Existing audits remain unchanged; their previously collected fields are not incorrectly treated as new analytics fields.

## TC 8.11 - Count failure does not block the download

**Covers:** AC8  
**Supersedes:** TC 4.10 (download portion)  
**Type:** Exception, parameterized Playwright end-to-end

**Preconditions**

- A test-only fault can refuse the count write before it begins for downloads on each source.

**Steps**

1. For each source in isolation, perform an otherwise-successful download while its increment fails.
2. Inspect the user-visible result, notifications, daily count, and container standard output.

**Expected outcome**

- The download succeeds and no telemetry-failure notification is shown.
- No count increases from the known pre-write drop; uncertain acknowledgement timeouts are covered by TC 7.6.
- Existing download audits continue under their pre-feature rules; US-007 reports the known drop in a bounded summary, not a per-download failure log.

## TC 8.12 - HEAD and ranged GET requests are excluded

**Covers:** AC1, AC2  
**Type:** Boundary, parameterized Playwright APIRequestContext

**Preconditions**

- Each serving file API can be reached with an authorized full-file GET, a GET carrying a `Range` header, and a HEAD request; their starting daily counts are known.

**Steps**

1. For each source in isolation, send HEAD and GET with `Range`; include a case where the downstream server ignores the requested range.
2. Send a full-file GET with no `Range` header and repeat it once as a full-file retry.
3. Inspect file API handoffs and the daily counts.

**Expected outcome**

- HEAD and every GET carrying `Range` add no download count, regardless of any downstream 206 or full-file response.
- Each successful authorized full-file GET without `Range` requests one increment; its retry counts again.

# Test Data Notes

- Use safe files controlled by the test environment.
- Mark automation deterministically; do not rely on timing or heuristic guesses.
- Use one known form per source to avoid ambiguous totals.

# Regression Notes

- Re-run Staff and Public attachment delivery and download audit coverage.
- Verify telemetry does not delay or block downloads.
- Verify no additional per-download stdout record is introduced; existing Staff and Public audit output is unchanged.
