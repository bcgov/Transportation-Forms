---
feature_id: FEAT-0031
story_id: US-012
test_id: TC-012
owner: Quality Analyst
status: draft
created: 2026-10-22 13:40:00
updated: 2026-10-22
depends_on: [US-001]
---

# Traceability

| Acceptance Criterion | Test Coverage |
|---|---|
| AC1 | TC 12.1 |
| AC2 | TC 12.2, TC 12.3 |
| AC3 | TC 12.4 |
| AC4 | TC 12.5, TC 12.6 |
| AC5 | TC 12.2, TC 12.7 |

# Test Cases

All UI and end-to-end cases use Playwright against the Product Owner-deployed local Staff and Public portals in the shared integrated browser. Direct create and workflow requests use Playwright `APIRequestContext`. Each case uses isolated forms and approved reservations. Verify persisted state through protected test support.

## TC 12.1 - Authorized new Draft receives an approved form number

**Covers:** AC1  
**Type:** Positive, Playwright UI and APIRequestContext

**Preconditions**

- An authorized `form:create` user and two isolated approved unused reservations with usable public numbers; all other form fields are valid.

**Steps**

1. Create one form through Add New Form with the first reservation.
2. Create another directly through the API with the second reservation.
3. Inspect both responses, persisted Drafts, reservation associations, and existing create audits.

**Expected outcome**

- Each form is created in Draft, linked to exactly its selected approved reservation, and returns the associated form number.
- Existing Business Area, ownership, and successful create-audit behavior is unchanged.

## TC 12.2 - Missing association is denied in UI and direct API

**Covers:** AC2, AC5  
**Type:** Negative, Playwright UI and APIRequestContext

**Preconditions**

- Authorized creator with otherwise valid fields and known starting form and audit row counts.

**Steps**

1. Attempt Add New Form without selecting a reservation; inspect validation and entered values.
2. In isolation, send otherwise-valid create requests with the association omitted and with explicit null.
3. Inspect responses and persisted forms and successful create events.

**Expected outcome**

- Every attempt is rejected; no Draft or successful create event is stored.
- UI feedback identifies the required reservation, is announced accessibly, and preserves unrelated input.
- Direct requests cannot bypass validation.

## TC 12.3 - Unusable reservations are rejected without a fallback

**Covers:** AC2  
**Type:** Negative, parameterized Playwright APIRequestContext

**Preconditions**

- Isolated malformed, unknown, deleted, pending, rejected, approved-but-used, and approved-without-usable-number reservation variants; all other fields valid.

**Steps**

1. Send one create request for each variant in isolation.
2. Inspect service response, form and audit rows, and reservation association.

**Expected outcome**

- Each create is rejected with no form, successful create event, or fallback number; existing reservation associations remain unchanged.

## TC 12.4 - Permission denial is unchanged

**Covers:** AC3  
**Type:** RBAC negative, Playwright UI and APIRequestContext

**Preconditions**

- Unauthenticated caller and authenticated user lacking `form:create`; each request names an approved unused reservation.

**Steps**

1. Attempt to open and submit Add New Form where applicable.
2. Submit a direct create request for each denied role.
3. Inspect responses and persistence.

**Expected outcome**

- Existing UI and API denials remain; no form, successful create event, or new association is stored.

## TC 12.5 - Grandfathered numberless forms keep existing workflow

**Covers:** AC4  
**Type:** Workflow regression, Playwright APIRequestContext

**Preconditions**

- Isolated legacy numberless forms in Draft, Pending Review, Archived, and Published states, with users satisfying each existing transition's permissions and state requirements.

**Steps**

1. Exercise an authorized existing save on a numberless Draft and permitted submit, approve or legacy publish, and restore transitions on separate appropriate fixtures.
2. Inspect resulting states, responses, and existing audit behavior.

**Expected outcome**

- No new form-number denial occurs; each transition still follows its existing authorization and state rules.
- The already-Published numberless form remains available under existing Public rules.

## TC 12.6 - Numberless legacy form has no Public engagement signal

**Covers:** AC4  
**Type:** Integration negative, Playwright Public UI and APIRequestContext

**Preconditions**

- A grandfathered numberless Public form is available under the existing Public portal rules.

**Steps**

1. Display the form through the available Public surface and inspect outgoing signal requests.
2. Attempt a Public engagement signal without a valid public form number.
3. Inspect counts and the Public pod's cache.

**Expected outcome**

- The existing Public availability is unchanged, but no qualified Public detail or source-link signal or daily count is generated; the form has no Public signal-cache entry.

## TC 12.7 - Required reservation feedback is usable on narrow screens

**Covers:** AC5  
**Type:** Accessibility and responsive, Playwright UI

**Preconditions**

- Authorized creator with valid other fields at desktop and narrow mobile viewport classes.

**Steps**

1. Attempt Save without a reservation using keyboard-only interaction at each viewport.
2. Inspect focus, accessible feedback, layout, and retained field values.
3. Select an approved unused reservation and retry Save.

**Expected outcome**

- Validation identifies the field without overlap or loss of unrelated input; keyboard and assistive technology users can correct it.
- Retry creates exactly one Draft linked to the approved number.

# Test Data Notes

- Use safe, isolated approved and invalid reservations and forms; never mutate PROD data.
- Keep the known legacy numberless fixtures distinct from new forms; the new create rule must not silently convert them.

# Regression Notes

- Re-run FEAT-0025 reservation approval, reuse, and form-number linkage tests and FEAT-0031 US-001 Add New Form and Business Area validation.
- Re-run existing submit, approve, legacy publish, restore, and Public form availability tests without adding a new publication check.
