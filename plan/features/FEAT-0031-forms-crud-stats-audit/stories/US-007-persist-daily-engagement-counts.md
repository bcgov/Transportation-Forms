---
feature_id: FEAT-0031
story_id: US-007
title: Persist anonymous daily engagement counts within bounded capacity
owner: Business Analyst
status: in_progress
created: 2026-10-16 13:30:00
updated: 2026-10-22 13:40:00
depends_on: []
---

# User Story

As a Product Owner, I want qualified download handoffs and accepted engagement signals recorded by one separate, bounded daily-count writer, so that best-effort statistics stay anonymous without disrupting ordinary portal use.

# Preconditions / Assumptions

- Split from former US-004 on 2026-10-16. This story owns only the persistence of daily counts. Qualification is owned by [US-008](US-008-count-successful-form-downloads.md) (downloads) and [US-009](US-009-capture-detail-and-link-engagement-signals.md) (detail views and source-link clicks). Retrieval is owned by [US-010](US-010-retrieve-authorized-engagement-statistics.md).
- Capture boundary confirmed by the Product Owner on 2026-10-16: the code that recognizes a qualified engagement is kept separate from the code that stores its daily count. This is an internal code boundary only; it introduces no queue, broker, separate service, or change to the approved direct atomic write.
- The Product Owner approved daily aggregates instead of per-action rows on 2026-10-14, and the concurrency strategy (atomic upsert, dedicated analytics pool with timeouts, drop over capacity) on 2026-10-15.
- Product Owner decisions on 2026-10-22: detail and link counts represent accepted best-effort signals, not verified human actions; known drops may reach 10% of writer attempts at an approved healthy peak; failures are reported in bounded summaries only, and an uncertain timeout is never retried.
- Collection may begin in TEST before PROD launch. TEST and PROD retain separate counts, with no transfer or backfill between environments.
- PCT means fixed UTC-07:00 year-round.
- Security controls follow OWASP ASVS, API Security Top 10 2023 (API4 Unrestricted Resource Consumption), and the Cheat Sheet Series for SQL Injection Prevention and Query Parameterization, Logging, and Denial of Service. Relevant weaknesses are CWE-89, CWE-117, and CWE-770.

# Test Coverage

- [TC-US-007 Persist daily engagement counts](../tests/TC-US-007-persist-daily-engagement-counts.md)

# Acceptance Criteria

## AC1 - Qualification is separate from count storage

**Given** a full-file download handoff has qualified under US-008, or a detail-view or source-link signal has been accepted under US-009  
**When** its count is recorded  
**Then** the qualifying path passes exactly one increment request containing only the form identifier, the metric, and the trusted portal source to the shared daily-count writer  
**And** the writer, not the qualifying path, determines the PCT day and performs persistence  
**And** the same writer and failure behavior apply to all three metrics and both sources  
**And** denied download handoffs and rejected or rate-limited signals never reach the writer; an accepted signal need not prove that a human completed the reported action.

## AC2 - Each increment is one atomic upsert and concurrent increments are retained

**Given** concurrent increment requests that have connections and complete before their timeouts  
**When** their daily count is written  
**Then** one parameterized atomic insert-or-increment statement creates the day's count at one or adds one to the existing count  
**And** all completed concurrent increments to the same count are retained, because the database serializes them on that single count  
**And** concurrent first-of-day increments create exactly one count, and no increment fails because another created the count first  
**And** no read-then-write, batching, in-memory aggregation of engagement counts, or external broker is used; capacity drops and uncertain timeouts follow AC5-AC6.

## AC3 - The PCT day is assigned at server receipt

**Given** an increment request is received just before or just after a fixed UTC-07:00 PCT midnight  
**When** it is written  
**Then** it is counted on the PCT calendar day of server receipt  
**And** no caller-supplied day or time influences the assigned day.

## AC4 - Retained daily counts stay anonymous and constrained

**Given** a qualified action has been counted  
**When** retained count data is inspected  
**Then** each retained count identifies only the form, metric, trusted portal source, PCT calendar day, and non-negative count  
**And** no individual action row, visitor name, email, account identifier, IP address, user-agent, screen resolution, or other unnecessary personal information is retained  
**And** the database itself rejects a metric or source outside the approved sets and any negative count, independently of endpoint validation.

## AC5 - Count-write problems are summarized without identity

**Given** a qualified action otherwise succeeds  
**When** its increment is known to be dropped or a database timeout leaves the commit outcome unknown  
**Then** the user action is unaffected (US-008 AC8 and US-009 AC7), and the increment is not retried  
**And** bounded summaries on container standard output group attempts by time window and server-defined reason code, distinguishing known drops from uncertain outcomes without per-form entries, visitor identity, raw request content, or individual-action rows  
**And** a known dropped increment changes no count, while an uncertain timeout may or may not have committed and is never described as definitely missing  
**And** no statistics completeness marker or warning is produced (statistics behavior is defined in US-010 AC9 and US-011 AC9).

## AC6 - Analytics database work is bounded under load

**Given** analytics count writes, from accepted signals or download handoffs, use a dedicated small analytics connection pool with a fixed concurrency ceiling and short lock and statement timeouts  
**When** the pool is exhausted or a write reaches its timeout  
**Then** a request refused before a write begins is known to be dropped without queuing or retry; a timed-out write is not retried and is classified by its known or uncertain outcome under AC5  
**And** ordinary portal database operations keep their own connections and remain available  
**And** affected attempts are reported through bounded, reason-broken-down operational summaries without visitor identity.

## AC7 - TEST and PROD counts remain separate

**Given** collection is active in TEST before PROD launch  
**When** a qualified action occurs in either environment  
**Then** only that environment's daily count increases  
**And** TEST counts are not transferred to PROD or included in PROD statistics.

## AC8 - The writer account is limited to one table and counts only go up

**Given** the writer connects with its dedicated database account  
**When** it increments a daily count  
**Then** the increment succeeds using only insert, update, and the minimum read that the atomic insert-or-increment statement needs on the daily-count table  
**And** the same account is refused any access to any other table, and is refused delete, truncate, schema change, and ownership on the daily-count table  
**And** the account is not a superuser and does not own the daily-count table, in every environment including local  
**And** the database itself rejects any update that would lower an existing count, independently of the writer's code.

## AC9 - Known drops stay within the approved healthy-peak allowance

**Given** engineering has proposed a normal peak workload and the Product Owner has approved that workload for TEST  
**When** an isolated healthy-peak load test sends qualified writer attempts without induced failures  
**Then** known drops divided by total writer attempts are at most 10% over the measured test run  
**And** confirmed writes, known drops, and uncertain outcomes are measured separately, without treating uncertain outcomes as confirmed writes or known drops  
**And** no percentage is claimed for browser actions whose signals never reached the server; above-peak traffic and faults remain governed by AC5-AC6.

# Business Rules

- **BR-001:** The three metrics are form downloads, source-link clicks, and form-detail views only; the two sources are Staff and Public only. (Former US-004 BR-001.)
- **BR-002:** Each completed qualified write increments the count for one form, metric, trusted portal source, and fixed UTC-07:00 PCT calendar day; repeated accepted signals and full-file handoffs are not deduplicated or stored as individual event rows. Known drops and uncertain timeouts may leave totals below actual activity. (Former US-004 BR-002; revised 2026-10-22.)
- **BR-003:** Qualification and count storage are separate. Qualifying paths decide whether an action counts and supply form, metric, and trusted source; the writer alone assigns the PCT day and persists one increment (Product Owner decision, 2026-10-16).
- **BR-004:** Count-increment problems never block the underlying user action. A bounded operational summary reports known drops separately from uncertain timeouts, by fixed reason code and time window, with no form or visitor details and no statistics completeness tracking (Product Owner decision, 2026-10-22).
- **BR-005:** TEST collection may start before PROD launch; PROD starts its own collection at launch, without backfill or TEST count migration. (Former US-004 BR-010.)
- **BR-006:** Daily counts from each environment's collection start remain retained for the full lifetime of All time reporting under US-010; no age-based expiration is currently approved. (Former US-004 BR-011.)
- **BR-007:** All analytics database access uses parameterized statements; no SQL text is built from request values. Each increment request performs one atomic increment-by-one on one daily count. (Former US-004 BR-017.)
- **BR-008:** Analytics writes use a dedicated small connection pool, separate from the ordinary application pool, with a fixed concurrency ceiling and short lock and statement timeouts. Increments refused before starting are dropped, not queued; timed-out writes are not retried because their commit outcome can be unknown. Engineering sets the starting ceiling and timeouts, tuned through TEST load results. (Former US-004 BR-018; revised 2026-10-22.)
- **BR-009:** Each increment is a single atomic insert-or-increment statement (Product Owner approved options 1 and 2 on 2026-10-15). Sharded counters are not in scope; they may be proposed only if TEST load results show contention on a single daily count. (Former US-004 BR-019.)
- **BR-010:** The writer uses its own dedicated, non-superuser database account in every environment, including local (Product Owner confirmed, 2026-10-16). It never uses the application account, which is a superuser in local deployment. Its only access is insert, update, and the minimum read required by the atomic insert-or-increment statement on the daily-count table. It has no delete, truncate, schema change, or ownership, and no access to any other table, view, sequence, or schema object. The daily-count table is owned by the migration account. The daily-count key is natural (form, metric, source, PCT day), so the writer needs no sequence access. ASSUMPTION (needs confirmation by engineering): the database-level rights needed only to reach that table, such as connecting to the database and using its schema, are not considered access to another table.
- **BR-011:** Counts only go up. The database rejects any update that lowers an existing count, in addition to rejecting negative counts (Product Owner decision, 2026-10-16).
- **BR-012:** There is no database rule linking daily counts to forms (Product Owner decision, 2026-10-16). Signals for made-up forms are rejected by the US-009 valid-form cache before reaching the writer. Counts for a form deleted or made unavailable can still be recorded on pods whose cache has not successfully refreshed; repeated check failures can extend that period indefinitely. They are retained, and US-010 never returns statistics for deleted forms.
- **BR-013:** Statistics retrieval under US-010 never uses the writer account.
- **BR-014:** Known drops may account for at most 10% of qualified writer attempts during an isolated, healthy peak workload proposed by engineering and approved by the Product Owner; uncertain outcomes are measured separately and cannot be called confirmed writes (Product Owner decision, 2026-10-22).

# RBAC / Permissions

## Roles allowed

- No user role invokes the daily-count writer directly. It is reached through authorized US-008 file handoffs and accepted US-009 signals; signal acceptance does not prove that the sender was authorized for an underlying form action.

## Roles denied

- Every external caller is denied direct access to the writer, including users with `form:stats`. No caller can read, decrement, reset, delete, or alter counts or schema through this story.
- Aggregate retrieval is governed by US-010, not by this story.

## Permission notes

- Event creation is a consequence of an already authorized or public action and introduces no user-facing event-write permission.
- Confirmed by the Product Owner on 2026-10-16 (Option A): user-facing RBAC does not apply to this internal writer. The US-008 and US-009 paths enforce their respective handoff or signal rules; the writer performs no permission check of its own and receives no user identity, consistent with AC4. Verified by TC 7.1.

# Data & Validation Rules

- Each environment retains one non-negative count per form, approved metric, trusted source (`Staff` or `Public`), and fixed UTC-07:00 PCT calendar day; no individual action record is required.
- The form, metric, source, and PCT day are unique together, so a day's count can exist only once.
- Stored metric and source values are restricted to the approved sets, and counts are non-negative. The database rejects any value outside those sets, independently of endpoint validation.
- The database rejects any update that lowers an existing count (BR-011).
- The form identifier in a daily count is not enforced by a database rule against the forms table (BR-012).
- Bounded operational summaries group writer problems by time window and server-defined reason code, distinguishing known drops from uncertain outcomes; no per-form or visitor details are logged by this feature.
- Logged values are limited to server-determined fields and reason codes, preventing log injection. The summary window and reason-code set are engineering configuration and must be documented and tested before acceptance.
- No TEST counts or pre-launch history are copied or synthesized into PROD.
- Retained daily counts are not pruned by age while All time reports from that environment's collection start.

# Edge Cases / Exceptions

- Known dropped increments cause undercounting; a timed-out write can have an unknown commit outcome. Both are reported in operational summaries only, not in the statistics UI.
- Many concurrent increments to one popular form's daily count wait on the same count; a lock timeout is not retried, and its known or uncertain outcome is reported accurately in summary.
- An increment received just after PCT midnight is counted on the new PCT day at server receipt.
- Daily aggregate storage grows with collection days, forms, metrics, and sources until a future retention policy changes the All time contract.
- Local deployment currently grants the application account superuser rights. The writer never uses that account; it uses its own non-superuser account locally too (AC8, Product Owner confirmed 2026-10-16), so privilege tests run locally are meaningful. Creating that account in local deployment is an engineering task outside this plan.
- A compromised writer account can only add to counts; it cannot read other tables, lower, reset, or delete counts.
- Counts can exist for forms deleted shortly before a pod's cache refreshed (US-009 AC18); they are retained and never returned for deleted forms (US-010). Made-up forms never reach the writer (US-009 AC12).

# Audit / Business Events

- Engagement counts are aggregate analytics data and do not appear in the user-facing form audit history.
- Failed or dropped increments do not appear in that history; they appear only in operational standard-output logs without visitor identity.
