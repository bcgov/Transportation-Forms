---
feature_id: FEAT-0031
story_id: US-008
title: Count successful form downloads by serving file API
owner: Business Analyst
status: done
created: 2026-10-16 13:30:00
updated: 2026-10-22 13:40:00
depends_on: [US-007]
---

# User Story

As a Product Owner, I want authorized full-file GET handoffs counted under the Staff or Public file API that served them, so that download statistics reflect file-API handoffs without changing how users download forms.

# Preconditions / Assumptions

- Split from former US-004 on 2026-10-16. This story owns download qualification; count persistence is owned by [US-007](US-007-persist-daily-engagement-counts.md). The proposed additional structured successful-download stdout record was withdrawn by the Product Owner on 2026-10-22.
- Downloads keep the existing file-delivery path and are counted server-side at handoff (Option B, Product Owner decision 2026-10-14). They never use the engagement endpoints defined in [US-009](US-009-capture-detail-and-link-engagement-signals.md).
- Portal source for downloads is the Staff or Public file API that serves the authorized response, including direct API requests. Request referrer and caller-supplied labels are not attribution rules.
- Existing Staff and Public portal permissions, form visibility, attachment delivery, and download audit behavior remain authoritative. A successful handoff does not prove the entire file was delivered.

# Test Coverage

- [TC-US-008 Count successful form downloads](../tests/TC-US-008-count-successful-form-downloads.md)
- [Staff qualification regression tests](../../../../apps/backend/tests/test_feature_FEAT_0031_us008_download_qualification.py) and [Public qualification regression tests](../../../../apps/public-backend/tests/test_feature_FEAT_0031_us008_download_qualification.py) cover handoff, exclusion, failure, attribution, and audit behavior. Deployed UI handoffs have been exercised; aggregate-count acceptance still requires an unambiguous before/after comparison.

# Acceptance Criteria

## AC1 - Successful form downloads are counted

**Given** a caller, including identifiable automation, makes an authorized GET without a `Range` header for a configured form attachment through a Staff or Public file API, whether via UI or directly  
**When** the Staff API opens the stream and hands off its response, or the Public API hands off its successful `X-Accel-Redirect` response  
**Then** one form-download increment is requested for that form and the serving Staff or Public API  
**And** denial, a failure before the relevant API handoff, HEAD, a GET with a `Range` header, and activation without that handoff do not qualify  
**And** a later Staff stream failure, Public edge or storage failure, or client disconnect does not reverse the count or count the same handoff again.

## AC2 - Repeated downloads are each counted

**Given** the same person or browser session downloads the same form attachment more than once  
**When** each full-file GET independently meets AC1, including a repeated full-file retry  
**Then** each download adds one to the daily download count  
**And** no person-level or session-level deduplication is applied.

## AC3 - Download source is the serving file API and cannot be spoofed

**Given** a download is made through either portal's UI or either file API directly  
**When** its daily count is updated  
**Then** the download is attributed to the serving Staff or Public file API  
**And** a caller cannot relabel the download as the other portal through an untrusted request value.

## AC4 - Identifiable bot downloads are counted

**Given** a successful authorized Staff or Public file-API handoff is made by identifiable automated traffic  
**When** qualification is evaluated  
**Then** the download counts under the serving source  
**And** bot classification does not affect download counting.

## AC5 - Existing attachment authorization remains authoritative

**Given** a user is denied an attachment or the form is unavailable under existing Staff or Public rules  
**When** the user attempts the download through UI or directly  
**Then** the existing denial remains in effect  
**And** no download count increases for the denied or failed attempt.

## AC6 - Existing download audits continue without a new analytics record

**Given** an authorized or denied Staff or Public file API request  
**When** download counting is enabled  
**Then** the existing Staff database download audit and Public download audit log keep their pre-feature behavior  
**And** no additional per-download stdout record or per-download analytics database row is created by this feature.

## AC7 - New download analytics retains no visitor identity

**Given** a qualified download has been counted or its increment has failed  
**When** new analytics data and operational summaries are inspected  
**Then** the US-007 daily count and bounded summaries contain no client IP, visitor name, email, account identifier, user-agent, screen resolution, or other visitor identity  
**And** the existing Staff and Public download audits remain separate and unchanged.

## AC8 - Count failure does not block the download

**Given** a file delivery otherwise succeeds  
**When** its daily count increment is known to be dropped or its outcome is uncertain under US-007  
**Then** the download still succeeds  
**And** no telemetry-failure notification is shown to the user  
**And** existing download audit behavior under AC6 remains unchanged.

## AC9 - Downloads are counted only at handoff

**Given** a user downloads a form through a Staff or Public portal UI  
**When** the download is performed  
**Then** the portal sends no engagement-endpoint signal for the download  
**And** the download is counted only by its serving file API at handoff.

# Business Rules

- **BR-001:** Staff and Public download sources are determined by the serving file API, never by an untrusted caller-supplied label. (Former US-004 BR-003, download portion.)
- **BR-002:** Direct Staff and Public file-API GETs without a `Range` header qualify when authorized and handed off. HEAD and ranged GETs do not count; each repeated full-file handoff counts. (Former US-004 BR-004, download portion; revised 2026-10-22.)
- **BR-003:** Staff downloads qualify at the stream handoff after successful S3 open; Public downloads qualify at the API's `X-Accel-Redirect` handoff. Later transfer, edge, storage, or client failures do not reverse the count (Product Owner decision, 2026-10-22).
- **BR-004:** Successful file-API handoffs count even for identifiable bots. (Former US-004 BR-008, download portion.)
- **BR-005:** No additional per-download stdout record is created. Existing Staff and Public download audits and their existing privacy and retention controls remain unchanged (Product Owner decision, 2026-10-22, superseding former US-004 BR-012).
- **BR-006:** Download counting uses the US-007 writer; count-increment failure never blocks the download. (Former US-004 BR-009, download portion.)

# RBAC / Permissions

## Roles allowed

- Users allowed by existing Staff or Public rules to download the attachment may generate a download count.
- Public anonymous callers, including direct API callers and identifiable bots, may generate Public download counts through already available authorized file responses.

## Roles denied

- Users denied the underlying attachment or form generate no download count for the denied attempt.
- No caller can change a download's portal source by supplying a portal label.
- No portal role may retrieve aggregate statistics through this story; retrieval is governed by US-010.

## Permission notes

- Download counting introduces no user-facing event-write permission.
- `form:stats` governs aggregate retrieval only and is not required to generate download counts.

# Data & Validation Rules

- A GET carrying `Range` is excluded even if the downstream service later ignores the range; HEAD is excluded because it is not a full-file GET handoff.
- No per-download analytics row is stored in the database; only the US-007 daily count changes.

# Edge Cases / Exceptions

- A download activation whose file response fails before handoff does not count.
- A download that begins a successful authorized response handoff but is interrupted by the client afterward still counts.
- A Public API handoff counts even if the subsequent edge fetch fails; a Staff stream handoff counts even if a later chunk fails.
- Automation identification does not affect downloads; successful file-API handoffs count regardless of bot classification.
- A download made while the client's Public signal limit (US-009 AC9) is exhausted is still counted, because downloads do not use the engagement endpoint.

# Audit / Business Events

- No new per-download analytics stdout record or user-facing form audit-history entry is produced; existing download audits are unchanged.
- Failed or denied download attempts do not appear in that history.
- Existing security logging and download audit behavior remain unchanged.

# Outstanding Questions

- Existing Staff and Public download audits and platform access logs may already contain IP addresses; their access and retention remain platform/privacy responsibilities, not a new analytics log created by this story.
