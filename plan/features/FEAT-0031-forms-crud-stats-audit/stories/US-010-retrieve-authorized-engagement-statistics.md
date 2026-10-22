---
feature_id: FEAT-0031
story_id: US-010
title: Retrieve authorized engagement statistics
owner: Business Analyst
status: draft
created: 2026-10-16 13:30:00
updated: 2026-10-22 13:40:00
depends_on: [US-007]
---

# User Story

As a Staff user with `form:stats`, I want the statistics service to return a form's engagement totals by metric, portal source, and approved period, so that authorized insight is accurate, protected, and consistent without exposing visitor identity.

# Preconditions / Assumptions

- Split from former US-005 on 2026-10-16. This story owns the service contract: authorization, period calculation, aggregation, response metadata, and caching. Presentation is owned by [US-011](US-011-display-engagement-statistics-in-form-insights.md).
- [US-007](US-007-persist-daily-engagement-counts.md) defines retained daily counts; [US-008](US-008-count-successful-form-downloads.md) and [US-009](US-009-capture-detail-and-link-engagement-signals.md) define qualified actions and trusted Staff/Public attribution.
- `form:stats` is a new effective permission. It is granted to seeded `admin`, denied to seeded `staff_viewer`, and may be explicitly assigned to custom roles.
- The permission independently authorizes statistics for every non-deleted form and does not require `form:read` or `form:edit`.
- PCT is an approved fixed UTC-07:00 timezone with no daylight-saving offset change.
- All periods end at the start of the current PCT day; today's activity is not yet included.

# Test Coverage

- [TC-US-010 Retrieve authorized engagement statistics](../tests/TC-US-010-retrieve-authorized-engagement-statistics.md)

# Acceptance Criteria

## AC1 - The statistics API uses standalone permission scope

**Given** an authenticated user has effective `form:stats`  
**When** the user requests statistics for any non-deleted form  
**Then** the service returns authorized aggregate statistics even when the user lacks `form:read` and `form:edit`  
**And** form ownership, Business Area, workflow state, and public visibility do not further restrict that statistics access  
**And** `form:stats` alone grants no Edit Form access.

## AC2 - Unauthorized callers are denied

**Given** an authenticated or unauthenticated caller lacks effective `form:stats`  
**When** the caller requests statistics directly  
**Then** the service denies the request and returns no protected totals or metadata, including period, PCT day cutoff, and collection start  
**And** a grant or revocation of `form:stats` takes effect on the caller's next statistics request.

## AC3 - Only the seven approved periods are accepted

**Given** a statistics request  
**When** its period is 1 day, 7 days, 30 days, 90 days, 180 days, 1 year, or All time  
**Then** the request is processed for that period  
**And** any other period value is rejected safely, without totals and without reflecting the supplied value.

## AC4 - Finite periods use complete previous PCT days

**Given** the server supplies one cutoff at the start of the current PCT day  
**When** a finite period is calculated  
**Then** its range covers the previous 1, 7, 30, 90, 180, or 365 complete PCT calendar days, respectively  
**And** the start of the first day is included and the cutoff at the start of today is excluded  
**And** leap years and daylight-saving dates do not change the 365-day year or the fixed UTC-07:00 day boundaries.

## AC5 - All time begins at this environment's collection start

**Given** All time is requested  
**When** statistics are returned  
**Then** totals include this environment's daily counts beginning when its collection started through the exclusive cutoff at the start of today in PCT  
**And** TEST counts are never included in PROD, and no pre-collection history is reconstructed  
**And** daily counts from collection start remain available for the full lifetime of this All time reporting range  
**And** the response includes this environment's collection start date for disclosure under US-011.

## AC6 - Each response returns exactly six correct totals

**Given** qualified daily counts exist across metrics, sources, and boundary days  
**When** statistics are requested for any approved period  
**Then** exactly one non-negative integer total is returned for each of the three metrics and two sources  
**And** totals include only qualified daily counts in the selected range  
**And** a range with no qualified daily counts returns six numeric zeros rather than an empty or unavailable result.

## AC7 - One server PCT day cutoff governs each response

**Given** a statistics request succeeds  
**When** its response is produced  
**Then** one server-supplied PCT day cutoff is used for all six totals and boundaries and is returned with the response  
**And** requests on the same PCT day share that cutoff, and a request after the next PCT midnight uses the new cutoff.

## AC8 - Unavailable statistics are reported distinctly

**Given** statistics are unsupported or unavailable for the requested form or period  
**When** the service handles the request  
**Then** it reports an unavailable condition that is distinct from a request error  
**And** no totals are returned with that condition.

## AC9 - Telemetry failures are not reported as completeness status

**Given** one or more qualified daily count increments failed during the requested period  
**When** retained totals are returned  
**Then** the response contains the numeric retained totals without an incomplete-data warning or completeness indicator  
**And** known drops and uncertain write outcomes are reported only in bounded, identity-free operational summaries under US-007.

## AC10 - Deleted and unknown forms expose no statistics

**Given** a caller with `form:stats` requests an unknown or deleted form  
**When** the service handles the request  
**Then** no statistics or form-existence detail is returned beyond the approved generic unavailable response.

## AC11 - Responses contain no visitor identity

**Given** any statistics response  
**When** its content is inspected  
**Then** it contains only aggregate totals and approved metadata  
**And** it contains no event-level visitor identity or unnecessary personal information.

## AC12 - Results are cached until the next PCT day without bypassing access checks

**Given** statistics for a form and period have been calculated for the current PCT day cutoff  
**When** any authorized user requests the same form and period before the next PCT midnight  
**Then** the same totals, cutoff, and data-through date are returned from the cache without recalculating from daily counts  
**And** `form:stats` permission, authentication, and deleted/unknown-form checks are still evaluated on every request before any cached value is returned  
**And** after the next PCT midnight, the first request calculates fresh totals using the new cutoff; no result cached under an earlier cutoff is returned  
**And** when the cache is emptied by a pod restart or drain, or an entry is evicted at the entry cap, the next request recalculates and returns the same totals, with no error.

# Business Rules

- **BR-001:** `form:stats` independently authorizes statistics for every non-deleted form. (Former US-005 BR-001.)
- **BR-002:** Seeded `admin` receives `form:stats`; seeded `staff_viewer` does not; custom roles receive it only by explicit assignment. (Former US-005 BR-002.)
- **BR-003:** The service independently denies retrieval to callers lacking `form:stats`, regardless of UI visibility. (Former US-005 BR-003, service portion.)
- **BR-004:** Metrics and sources are limited to the three metrics and two sources defined by US-007. (Former US-005 BR-004.)
- **BR-005:** Finite windows cover the previous 1, 7, 30, 90, 180, or 365 complete fixed UTC-07:00 PCT calendar days; they include the first day's start and exclude today's start. (Former US-005 BR-005.)
- **BR-006:** All time begins at the current environment's collection start, ends before today's PCT start, requires no backfill, and returns its start date for disclosure; TEST counts never appear in PROD. (Former US-005 BR-006.)
- **BR-007:** Each response uses one server-supplied PCT day cutoff for every returned total and boundary. (Former US-005 BR-008, service portion.)
- **BR-008:** Valid no-activity results return six zeros; unavailable and error conditions remain distinct. (Former US-005 BR-009, service portion.)
- **BR-009:** Known drops and uncertain write outcomes leave retained totals returned without completeness status or warnings; US-007 requires bounded operational summaries on standard output (former US-005 BR-010, service portion; revised 2026-10-22).
- **BR-010:** Daily counts from each environment's collection start have no age-based expiration while All time reports from that start. A future retention limit requires a separately approved change to this reporting rule. (Former US-005 BR-011.)
- **BR-011:** Statistics results may be cached per environment, form, and period, keyed to the PCT day cutoff, and expire at the next PCT midnight (Product Owner approved option 6 on 2026-10-15). Because every period ends before today, today's increments never change a cached result. The cache never stores or skips authorization decisions. It is an in-memory, per-pod cache with a fixed maximum entry count and least-recently-used eviction; engineering sets the starting cap. Cache loss or eviction only causes recalculation, never different totals. (Former US-005 BR-012.)

# RBAC / Permissions

## Roles allowed

- Seeded `admin` receives `form:stats` by default.
- Any authenticated user whose current active assigned roles supply effective `form:stats` may retrieve statistics for every non-deleted form, including stats-only custom roles.

## Roles denied

- Seeded `staff_viewer` is denied unless another active assigned custom role explicitly supplies `form:stats`.
- Authenticated users lacking effective `form:stats` and unauthenticated callers receive no statistics data.
- No caller receives statistics for deleted or unknown forms.

## Permission notes

- `form:stats` does not require `form:read`, `form:edit`, ownership, Business Area membership, workflow state, or public visibility.
- A stats-only user may use the authorized API but receives no new Edit page access.
- `form:stats` grants no form mutation, audit, approval, publication, administration, or visitor-data capability.

# Data & Validation Rules

- Responses contain six non-negative integer totals, selected period, one PCT day cutoff, and collection start when applicable; no completeness status is returned.
- Period input accepts only the seven approved values; unsupported values are rejected safely.
- PCT means fixed UTC-07:00 year-round.
- Daily aggregate counts are retained from each environment's collection start for the full lifetime of the current All time reporting range.
- Aggregate responses contain no event-level visitor identity or unnecessary personal information.
- Statistics retrieval reads daily counts with read-only database access and never uses the US-007 writer account (US-007 BR-013, Product Owner direction 2026-10-16).

# Edge Cases / Exceptions

- A qualified action at the finite start contributes to the included day; an action at today's PCT start contributes to today and is excluded until tomorrow.
- A TEST count cannot contribute to PROD statistics, even if the action occurred on the same PCT calendar day as PROD launch.
- Leap years do not change the 365-day definition of 1 year.
- A custom role can receive `form:stats` without form read/edit and can then retrieve every non-deleted form's aggregates by identifier.
- A failed daily count increment may make retained totals lower than actual activity; the statistics response does not label affected periods as incomplete.
- A form deleted after its statistics were cached returns the generic unavailable response, not the cached totals.
- Daily counts can be recorded for a form after it is deleted on pods whose valid-form cache has not successfully refreshed (US-009 AC18); repeated failed checks can extend this indefinitely. Those counts are retained, because no database rule links counts to forms (US-007 BR-012), but are never returned for deleted forms (AC10).
- An increment received just before PCT midnight that commits after the first post-midnight result is cached is left out of that cached result until the cache expires at the following PCT midnight. US-007's short write timeouts keep this window to seconds (Product Owner accepted, 2026-10-15). This window is an accepted limitation and is not asserted by a deterministic test.
- Each backend pod holds its own in-memory cache with a fixed maximum entry count, evicting least-recently-used entries; no PVC, Redis, or other shared cache is used (Product Owner approved, 2026-10-15). Pods calculate results separately. Results match except when a late increment from the midnight window above commits between two pods' calculations, in which case they can differ by that increment until the next PCT midnight.
- A pod restart, drain, or eviction empties that pod's cache; its next request for each form and period recalculates from daily counts with the same result rules.

# Audit / Business Events

- Requesting statistics creates no user-facing form audit-history event.
- Statistics responses expose aggregate counts only and never visitor identity.
- Existing security logging for denied statistics requests remains operational but is not shown in form activity history.
