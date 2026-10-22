---
feature_id: FEAT-0031
story_id: US-007
test_id: TC-007
owner: Quality Analyst
status: draft
created: 2026-10-16 13:30:00
updated: 2026-10-22
depends_on: [US-008, US-009]
---

# Traceability

| Acceptance Criterion | Test Coverage |
|---|---|
| AC1 | TC 7.1 |
| AC2 | TC 7.2, TC 7.3 |
| AC3 | TC 7.4 |
| AC4 | TC 7.5 |
| AC5 | TC 7.6 |
| AC6 | TC 7.7, TC 7.8 |
| AC7 | TC 7.9 |
| AC8 | TC 7.10, TC 7.11 |
| AC9 | TC 7.12 |

Legacy mapping: TC 4.10 (writer portion), TC 4.11 (count portion), TC 4.13, TC 4.14, TC 4.28, TC 4.30, and TC 4.31 from the former TC-US-004. TC 7.1, TC 7.4, TC 7.10, and TC 7.11 are new.

# Test Cases

All portal-action cases use Playwright against the Product Owner-deployed local Staff and Public portals in the shared integrated browser. Use Playwright `APIRequestContext` for direct, concurrency, and load cases. Each case uses isolated daily counts. Inspect counts only through protected test support. Load and pool cases run only in local or TEST.

## TC 7.1 - All qualifying paths use the shared writer and unqualified activity never reaches it

**Covers:** AC1  
**Supersedes:** New (capture boundary, Product Owner decision 2026-10-16)  
**Type:** Positive and negative boundary, Playwright UI and APIRequestContext

**Preconditions**

- In TEST, protected test support can observe writer invocation counts by metric and source without retaining visitor or per-action production analytics data.
- A test-only fault makes writer attempts known to be dropped; starting daily counts are known.

**Steps**

1. With the fault enabled, perform one qualified Staff download, one Public detail view, and one Public source-link activation, each in an isolated context.
2. Still with the fault enabled, attempt one denied download, one signal with a mismatched origin, and one malformed signal.
3. Inspect user outcomes, daily counts, writer invocation counts, and the bounded operational summary.

**Expected outcome**

- Each qualified action in step 1 succeeds for the user and makes exactly one observed writer attempt for its metric and source; no count changes because the test fault rejects writes before they begin.
- Each attempt in step 2 makes no writer attempt.
- The summary reports known drops by fixed reason code without individual action or form entries; all three metrics use the shared writer.

## TC 7.2 - First increment of a day creates exactly one count

**Covers:** AC2  
**Supersedes:** TC 4.31  
**Type:** Concurrency boundary, Playwright APIRequestContext

**Preconditions**

- No daily count exists yet for a form, metric, source, and today's PCT day; analytics pool capacity and timeouts permit all 10 writes to complete, and the Public signal limiter is not the bottleneck.

**Steps**

1. Release 10 valid signals for that combination concurrently using a deterministic test barrier.
2. Inspect the analytics rows for that combination.

**Expected outcome**

- Exactly one daily count exists for that combination, with value 10.
- No signal fails because another created the row first.

## TC 7.3 - Concurrent qualified actions do not lose increments

**Covers:** AC2  
**Supersedes:** TC 4.14  
**Type:** Concurrent actions, Playwright end-to-end

**Preconditions**

- Two isolated portal contexts can perform the same qualified action for one form, metric, source, and PCT day.
- The starting daily count is known, both actions can be released together using a deterministic test barrier, and neither write hits the capacity ceiling or a timeout.

**Steps**

1. Release both qualified actions concurrently.
2. After both user actions succeed, inspect the daily count.

**Expected outcome**

- The daily count increases by two; neither qualified action loses its increment.
- No individual action rows or visitor identity are retained.

## TC 7.4 - PCT day is assigned at server receipt across midnight

**Covers:** AC3  
**Supersedes:** New (former US-004 edge case)  
**Type:** Boundary, Playwright APIRequestContext

**Preconditions**

- Server time can be fixed deterministically; starting counts for two adjacent PCT days are known.

**Steps**

1. Fix server time one second before fixed UTC-07:00 midnight and send one valid signal.
2. Fix server time exactly at fixed UTC-07:00 midnight and send one valid signal.
3. Repeat step 2 with a caller-supplied date field in the body.
4. Inspect counts for both PCT days.

**Expected outcome**

- The step 1 signal increments the earlier PCT day; the step 2 signal increments the new PCT day.
- The step 3 signal is rejected under US-009 AC11 and changes no count.
- Daylight-saving dates do not move the boundary.

## TC 7.5 - Retained counts are anonymous and constrained

**Covers:** AC4  
**Supersedes:** TC 4.11 (retained-count portion)  
**Type:** Privacy and data-integrity contract, Playwright APIRequestContext and data inspection

**Preconditions**

- Authenticated Staff and anonymous Public actions have been counted.
- Protected test support can attempt direct writes to the count store.

**Steps**

1. Inspect the retained count data for all fields.
2. Search for names, emails, account IDs, IP addresses, user agents, screen resolution, and request identity fields.
3. Through protected test support, attempt to store an unknown metric, an unknown source, and a negative count.

**Expected outcome**

- Retained counts contain only form, metric, trusted source, PCT day, and count; no individual action rows exist.
- No visitor identity field or value is found.
- The database rejects each step 3 write.

## TC 7.6 - Known drops and uncertain timeouts have bounded, distinct summaries

**Covers:** AC5  
**Supersedes:** TC 4.10 (writer portion), TC 4.11 (failure-output portion)  
**Type:** Exception and privacy, parameterized Playwright end-to-end

**Preconditions**

- A protected test fixture can deterministically refuse writes before they begin and separately induce an acknowledgement timeout after a write may have committed.
- Container standard output, starting counts, and the US-010 response can be inspected.

**Steps**

1. For each metric/source variant, generate known pre-write drops; separately generate an acknowledgement timeout, both within one configured summary window.
2. Inspect counts, windowed stdout summaries, and the US-010 response for a period containing that day.
3. Repeat an incident over multiple windows and inspect that summary volume remains bounded by the configured windows and finite reason codes.

**Expected outcome**

- Known drops change no count. A timed-out increment is not retried and may contribute zero or one; it is classified as an uncertain outcome, not a definite miss.
- Each window's summary distinguishes fixed reason codes and known drops from uncertain outcomes; no individual form, visitor, IP, raw request content, or unbounded per-failure line appears.
- The statistics response contains no completeness marker or warning.

## TC 7.7 - Analytics write ceiling protects ordinary database use

**Covers:** AC6  
**Supersedes:** TC 4.28  
**Type:** Load and resilience, Playwright APIRequestContext

**Preconditions**

- In TEST, the analytics write ceiling is reduced through a test-only setting; database contention on one daily count can be induced; valid requests use trusted isolated clients or the authenticated Staff endpoint so Public per-replica edge limiting is not the bottleneck.

**Steps**

1. Send concurrent valid signals above the analytics write ceiling while running ordinary form list, detail, save, and download requests.
2. Inspect user-facing response times and outcomes, daily counts, and operational logs.

**Expected outcome**

- Ordinary requests succeed within their normal response-time range.
- Signals over the ceiling are dropped without queuing; counts increase only for completed increments.
- Drop logging is summarized and bounded, not one line per dropped signal, and contains no visitor identity.

## TC 7.8 - Analytics pool exhaustion and lock timeouts do not take ordinary connections

**Covers:** AC6  
**Supersedes:** TC 4.30  
**Type:** Resilience, Playwright APIRequestContext

**Preconditions**

- In TEST, the analytics daily-count row for one form is held locked by a test fixture, so analytics writes wait until their lock timeout.

**Steps**

1. Send enough concurrent valid signals and downloads to occupy every analytics pool connection.
2. While they wait, run ordinary form list, detail, save, and download requests.
3. Release the lock and inspect counts and logs.

**Expected outcome**

- Ordinary requests succeed within their normal response-time range; downloads succeed even when their increment is dropped.
- Refused pre-write attempts are known drops; timed-out writes are not retried and are reported as known or uncertain according to their observed outcome. Logs contain only bounded, reason-coded summaries.

## TC 7.9 - TEST and PROD counts remain isolated

**Covers:** AC7  
**Supersedes:** TC 4.13  
**Type:** Environment boundary, Playwright end-to-end in isolated TEST fixtures

**Preconditions**

- Isolated TEST fixtures represent separate TEST and PROD analytics contexts, with collection enabled first in the TEST context.
- Matching form, metric, source, and PCT day can be compared in each context without accessing live PROD.

**Steps**

1. Perform one qualified action in the TEST context and inspect both contexts' daily counts.
2. Enable collection in the PROD context, perform one qualified action there, and inspect both counts again.

**Expected outcome**

- The TEST action increases only the TEST count; the PROD action increases only the PROD count.
- No TEST count is transferred to PROD or included in PROD statistics.

## TC 7.10 - Writer account is limited to the daily-count table

**Covers:** AC8  
**Type:** Security privilege boundary, database-level check run from Playwright test support in local and TEST

**Preconditions**

- The writer's dedicated database account credentials are available to protected test support only.
- A known daily count exists; the forms table and one other application table contain known rows.

**Steps**

1. Using the writer account, perform one atomic insert-or-increment on the known daily count.
2. Using the writer account, attempt in isolation: read the forms table; read another application table; write to another application table; read an application view; use an application sequence; delete a daily count; truncate the daily-count table; alter the daily-count table; create a table.
3. Check whether the writer account is a superuser and whether it owns the daily-count table, in local and in TEST.
4. Check that the writer's connections in local and TEST use the writer account, not the application account.
5. Inspect the daily-count table and the other tables.

**Expected outcome**

- Step 1 succeeds and the count increases by one.
- Every step 2 attempt is refused with a permission error, and no data or schema changes.
- In both local and TEST, the writer account is not a superuser and does not own the daily-count table.
- In both local and TEST, every writer connection uses the writer account.

## TC 7.11 - The database rejects any decrease

**Covers:** AC8  
**Type:** Data integrity negative, database-level check run from Playwright test support in local and TEST

**Preconditions**

- A known daily count of 5.
- Both the writer account and the migration account are available to protected test support only.

**Steps**

1. Using the writer account, attempt to update the count to 4, then to 0.
2. Using the migration account, attempt to update the count to 4.
3. Using the writer account, perform one atomic increment.
4. Inspect the count.

**Expected outcome**

- Steps 1 and 2 are rejected by the database and the count remains 5.
- Step 3 succeeds and the count becomes 6.

## TC 7.12 - Healthy-peak known-drop percentage is at most 10%

**Covers:** AC9  
**Type:** Quantitative performance acceptance, Playwright APIRequestContext in TEST

**Preconditions**

- Engineering has documented a representative peak workload, including duration, concurrency, form/metric/source mix, and a hot daily-count row; the Product Owner has approved it for this test.
- Protected test support records writer attempts, confirmed increments, known pre-write drops, and uncertain outcomes without visitor identity. No faults are induced.

**Steps**

1. Execute the approved workload through actual Staff and Public entry points, keeping Public edge traffic within its independently configured signal-rate budget.
2. Compare writer-attempt totals with confirmed increments, known drops, and uncertain outcomes, and inspect ordinary portal request outcomes.

**Expected outcome**

- Known drops divided by writer attempts are at most 10% for the whole measured healthy-peak run; the numerator and denominator are reported as integers.
- Uncertain outcomes are reported separately, never counted as confirmed writes or as known drops, and no browser action that failed to reach an endpoint is included in the writer-attempt denominator.
- Completed writes preserve atomicity; ordinary portal requests continue to work under the separate pool.

# Test Data Notes

- Use one known form per metric/source combination to avoid ambiguous totals; compare daily counts before and after each action.
- Fault, ceiling, lock, and time controls are test-only settings available in local or TEST only.
- The 10% rule cannot be signed off until the Product Owner approves engineering's proposed peak workload and the configured writer and Public edge limits are recorded for a reproducible run.
- Inspect aggregate data through isolated fixtures or protected test support, never through an unauthorized production route.
- Writer and migration account credentials used by TC 7.10 and TC 7.11 come from the environment's secrets and are never written into test files or logs.

# Regression Notes

- Verify existing migrations still run under the migration account after the daily-count table ownership and decrease rule are added.
- Verify the local deployment's superuser application account is not used by the writer.
- Verify the ordinary application connection pool size and behavior are unchanged by the separate analytics pool.
- Verify retries and repeated actions add one to the daily count per qualified action rather than double-counting one action.
- At PROD deployment, verify PROD counts start independently; do not use live PROD actions for pre-launch TEST acceptance.
