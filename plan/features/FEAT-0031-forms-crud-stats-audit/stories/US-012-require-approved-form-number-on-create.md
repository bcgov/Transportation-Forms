---
feature_id: FEAT-0031
story_id: US-012
title: Require an approved form number reservation on new forms
owner: Business Analyst
status: draft
created: 2026-10-22 13:40:00
updated: 2026-10-22 13:40:00
depends_on: [US-001]
---

# User Story

As a Staff user authorized to create forms, I want to associate an approved, unused form-number reservation when I create a form, so that newly created forms have the public number needed for Public engagement signals.

# Preconditions / Assumptions

- Product Owner decisions on 2026-10-22 expand FEAT-0031 beyond its original intake's publication-rule exclusion, but require no new publication check or workflow step. The new requirement is enforced on creation, including Draft creation, through the existing approved-reservation mechanism.
- Existing `form:create`, Business Area, reservation approval and reuse, and create-form validation rules remain authoritative. The create API currently accepts an optional `form_number_reservation_id`; this story makes a valid approved association mandatory for new forms, not for legacy forms or Edit.
- Existing numberless Draft, Pending Review, Archived, and Published forms keep their current workflow and Public availability. No new Edit Form number-assignment capability, retroactive validation, or data migration is authorized. Public signals for numberless legacy forms are excluded under [US-009](US-009-capture-detail-and-link-engagement-signals.md).

# Test Coverage

- [TC-US-012 Require approved form number on create](../tests/TC-US-012-require-approved-form-number-on-create.md)

# Acceptance Criteria

## AC1 - Authorized creation associates an approved number

**Given** a Staff user has effective `form:create`, meets existing creation prerequisites, and selects an approved unused form-number reservation  
**When** the user creates a valid form through the UI or directly through the create API  
**Then** the created Draft is linked to that reservation and returns its form number under the existing Staff response contract  
**And** existing Business Area, ownership, audit, and validation behavior remains in effect.

## AC2 - Missing or unusable reservation blocks creation

**Given** a Staff user has otherwise valid new-form data  
**When** the submitted reservation association is missing, null, malformed, unknown, deleted, not approved, already linked to a non-deleted form, or has no usable public form number  
**Then** the UI and service reject creation without saving a form or a successful create event  
**And** the UI preserves entered values and gives accessible field-linked feedback explaining that an approved unused form number is required.

## AC3 - Existing create authorization still applies

**Given** a caller is unauthenticated or lacks effective `form:create`  
**When** the caller tries to create a form, even with a valid approved reservation  
**Then** existing UI access and direct service denial remain in effect  
**And** no form or successful create event is stored and no reservation is linked by that attempt.

## AC4 - No new publication or edit rule

**Given** an existing numberless form is in Draft, Pending Review, Archived, or Published state  
**When** an authorized user follows an existing save or workflow transition, or a reviewer approves, publishes, or restores it  
**Then** the existing edit and workflow permissions and state rules still apply without a new form-number prerequisite  
**And** existing numberless Published forms remain available under their current Public rules but generate no Public detail or source-link signals until an independently approved process gives them a public number  
**And** this story adds no number-assignment field to the Edit API.

## AC5 - The new-form constraint is consistent across entry points

**Given** a Staff user opens Add New Form or sends a direct create request  
**When** the user attempts to save without a valid approved unused reservation  
**Then** neither entry point creates a Draft; bypassing the UI cannot bypass the service validation  
**And** keyboard and narrow-screen users receive the same accessible validation and can correct the selection without re-entering unrelated fields.

# Business Rules

- **BR-001:** A new form, including a Draft, requires an approved unused form-number reservation whose public form number is usable (Product Owner decision, 2026-10-22).
- **BR-002:** `form:create` and all existing creation prerequisites continue to apply. A valid number never grants authorization.
- **BR-003:** Numberless legacy forms are grandfathered regardless of workflow state. No publication check, Edit Form number-assignment change, or retroactive migration is introduced (Product Owner decision, 2026-10-22).
- **BR-004:** Public signals use the existing public form number; numberless legacy forms have no Public signal-cache entry under US-009.

# RBAC / Permissions

## Roles allowed

- Staff users with effective `form:create` who satisfy existing creation requirements may create a form with an approved unused reservation.

## Roles denied

- Unauthenticated callers and users without effective `form:create` cannot create a form even with a valid reservation.
- A creator cannot create a form with a missing or invalid association, regardless of other permissions.

## Permission notes

- This story creates no new permission and does not change existing reservation approval, workflow, Edit, or publication authorization.

# Data & Validation Rules

- `form_number_reservation_id` must identify an existing, non-deleted, approved reservation with a usable public number that is not linked to another non-deleted form.
- Creation without that association is invalid in both UI and service; legacy nullable associations remain readable and retain current behavior.

# Edge Cases / Exceptions

- An approved reservation already used by a different non-deleted form is rejected. Failed creation does not reserve it or create a form.
- If the reservation becomes unavailable before creation completes, the attempted create fails and keeps user input for correction; no fallback number is generated.
- A numberless legacy form may still enter Published through existing workflow; no Public engagement signal is sent for it under US-009.

# Audit / Business Events

- A successful create retains the existing form-creation audit behavior. A denied or invalid attempt creates no successful form audit event.
