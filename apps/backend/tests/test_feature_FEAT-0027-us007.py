"""
FEAT-0027 — US-007 (Approvals: compact Form Number Reservation "View" popup).

Static assertions against the internal ``apps/frontend`` source tree. Mirrors
the FEAT-0027 static-regression pattern established for US-001..US-006 /
US-008. No browser is required.

Traceability: TC-US-007 (TC 7.1..TC 7.10).
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APPS_DIR = Path(__file__).resolve().parents[2]
FRONTEND = APPS_DIR / "frontend"

RESERVATION_POPUP = FRONTEND / "js" / "shared" / "reservation-view-popup.js"
APPROVALS_VIEW = FRONTEND / "js" / "views" / "approvals.js"
FORM_POPUP = FRONTEND / "js" / "shared" / "form-view-popup.js"
INDEX_HTML = FRONTEND / "index.html"


def _read(path: Path) -> str:
    assert path.exists(), f"Missing frontend file: {path}"
    return path.read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"(?m)//.*$", "", src)
    return src


# ===========================================================================
# TC 7.1 — View button on every reservation row
# ===========================================================================


class TestUS007ReservationViewButton:
    def test_reservation_row_has_view_button(self):
        """AC1 / TC 7.1 — the Form Number Reservations section renders a
        View button carrying data-action="reservation-view"."""
        src = _read(APPROVALS_VIEW)
        assert 'data-action="reservation-view"' in src, (
            "Reservation rows must render a View button "
            '(data-action="reservation-view") — US-007 AC1'
        )

    def test_inline_reservation_controls_remain(self):
        """AC3 / CC-BR-04 — the existing inline Approve / Request Changes /
        Reject controls MUST remain."""
        src = _read(APPROVALS_VIEW)
        for action in ("open-approve", "open-request-changes", "open-reject"):
            assert f'data-action="{action}"' in src, (
                f"Inline reservation control {action} MUST remain — CC-BR-04"
            )

    def test_view_click_opens_reservation_popup(self):
        """AC1 / TC 7.1 — the delegated handler opens the compact reservation
        popup and forwards the opener element for focus return (AC8)."""
        src = _strip_js_comments(_read(APPROVALS_VIEW))
        pattern = re.compile(
            r"openReservationViewPopup\s*\(\s*\{[^}]*reservationId[^}]*"
            r"openerElement[^}]*\}\s*\)",
            re.DOTALL,
        )
        assert pattern.search(src), (
            "Approvals view must open the reservation popup with reservationId "
            "and openerElement — US-007 AC1 / AC8"
        )

    def test_approvals_imports_reservation_popup(self):
        src = _read(APPROVALS_VIEW)
        assert "from '../shared/reservation-view-popup.js'" in src, (
            "approvals.js must import the reservation-view-popup module"
        )


# ===========================================================================
# TC 7.2 — Popup shows exactly the four required fields
# ===========================================================================


class TestUS007PopupFields:
    def test_popup_renders_four_required_fields(self):
        """AC2 / TC 7.2 — Form Number, Method, Reserved By, Created."""
        src = _read(RESERVATION_POPUP)
        for hook in (
            'data-testid="reservation-form-number"',
            'data-testid="reservation-method"',
            'data-testid="reservation-reserved-by"',
            'data-testid="reservation-created"',
        ):
            assert hook in src, f"Popup must render {hook} — US-007 AC2"

    def test_method_maps_legacy_code_without_crashing(self):
        """AC2 edge case — unknown / legacy method codes render as-is."""
        src = _strip_js_comments(_read(RESERVATION_POPUP))
        assert "_formatMethod" in src, "Popup must map the numbering method"
        # Fallback branch returns the raw code (or an em dash) rather than
        # throwing on an unknown value.
        assert re.search(r"return\s+method\s*\|\|", src), (
            "Unknown method codes must render as-is — US-007 edge case"
        )

    def test_popup_does_not_render_form_details(self):
        """AC10 / TC 7.10 — the popup exposes no form fields other than the
        reservation's form number, and never fetches a form endpoint."""
        src = _strip_js_comments(_read(RESERVATION_POPUP))
        assert "/forms/" not in src, (
            "Reservation popup must not call any /forms endpoint — US-007 AC10"
        )
        assert "download" not in src.lower(), (
            "Reservation popup must not render form downloads — US-007 AC10"
        )

    def test_popup_fetches_reservation_detail_endpoint(self):
        """TC 7.10 — the only data source is the reservation detail endpoint."""
        src = _strip_js_comments(_read(RESERVATION_POPUP))
        assert "/reservations/${encodeURIComponent(reservationId)}" in src, (
            "Popup must fetch the reservation detail endpoint"
        )


# ===========================================================================
# TC 7.3 — Actions reuse the existing inline server flow
# ===========================================================================


class TestUS007ActionsReuseInlineFlow:
    def test_popup_footer_exposes_three_action_buttons(self):
        """AC3 — Approve, Request Changes, Reject buttons are rendered."""
        src = _read(RESERVATION_POPUP)
        for action in (
            "reservation-view-approve",
            "reservation-view-request-changes",
            "reservation-view-reject",
        ):
            assert f'data-action="{action}"' in src, (
                f"Popup must render {action} button — US-007 AC3"
            )

    def test_popup_delegates_actions_via_events(self):
        """AC3 / CC-BR-04 — the popup dispatches events instead of calling the
        server directly, so approvals.js reuses the SAME confirmation modal and
        endpoint as the inline controls."""
        src = _strip_js_comments(_read(RESERVATION_POPUP))
        assert "reservation-view-popup:" in src, (
            "Popup must hand actions back via reservation-view-popup:* events"
        )
        # The popup itself must NOT POST to the reservation action endpoints.
        assert "approve" not in src or "method: 'POST'" not in src, (
            "Popup must not POST directly — it reuses the inline flow"
        )

    def test_approvals_wires_popup_action_events_to_existing_modals(self):
        """AC3 — approvals.js maps the popup events onto the existing modal
        openers (openApproveModal / openRequestChangesModal / openRejectModal)."""
        src = _strip_js_comments(_read(APPROVALS_VIEW))
        assert "reservation-view-popup:approve" in src
        assert "reservation-view-popup:request-changes" in src
        assert "reservation-view-popup:reject" in src
        assert "openApproveModal(" in src
        assert "openRequestChangesModal(" in src
        assert "openRejectModal(" in src


# ===========================================================================
# TC 7.4 — RBAC: open the popup
# ===========================================================================


class TestUS007OpenRbac:
    def test_popup_gated_by_reservation_read(self):
        """AC4 / TC 7.4 — the popup opens only if the user holds
        reservation:read."""
        src = _strip_js_comments(_read(RESERVATION_POPUP))
        assert "hasPermission('reservation:read')" in src, (
            "Popup open must be gated by reservation:read — US-007 AC4"
        )


# ===========================================================================
# TC 7.5..7.8 — RBAC: per-action button state
# ===========================================================================


class TestUS007ActionRbac:
    def test_approve_button_gated_by_reservation_approve(self):
        """AC5 / TC 7.5 — Approve enabled only with reservation:approve."""
        src = _strip_js_comments(_read(RESERVATION_POPUP))
        assert "hasPermission('reservation:approve')" in src

    def test_request_changes_gated(self):
        """AC6 / TC 7.7."""
        src = _strip_js_comments(_read(RESERVATION_POPUP))
        assert "hasPermission('reservation:request_changes')" in src

    def test_reject_gated(self):
        """AC7 / TC 7.8."""
        src = _strip_js_comments(_read(RESERVATION_POPUP))
        assert "hasPermission('reservation:reject')" in src

    def test_inline_buttons_also_gated(self):
        """Inline row controls carry the same permission gating (decision:
        gate inline buttons for consistency)."""
        src = _strip_js_comments(_read(APPROVALS_VIEW))
        assert "hasPermission('reservation:approve')" in src
        assert "hasPermission('reservation:request_changes')" in src
        assert "hasPermission('reservation:reject')" in src

    def test_self_approval_future_proofed_and_off(self):
        """AC5 — self-approval SoD is future-proofed but disabled today so the
        popup matches the existing inline control's behaviour."""
        src = _strip_js_comments(_read(RESERVATION_POPUP))
        assert "SELF_APPROVAL_ENFORCED" in src, (
            "A toggle must exist to enable reservation self-approval SoD later"
        )
        assert re.search(r"SELF_APPROVAL_ENFORCED\s*=\s*false", src), (
            "Self-approval SoD must be OFF today (match existing behaviour) — AC5"
        )


# ===========================================================================
# TC 7.9 — Focus return + separate modal (AC8 / AC10)
# ===========================================================================


class TestUS007FocusAndIsolation:
    def test_focus_returns_to_opener_on_close(self):
        """AC8 / TC 7.9 — focus returns to the View button on close."""
        src = _strip_js_comments(_read(RESERVATION_POPUP))
        assert "hidden.bs.modal" in src, (
            "Popup must restore focus on the Bootstrap hidden event — US-007 AC8"
        )
        assert "_openerElement" in src

    def test_dedicated_modal_element_exists(self):
        """AC10 — the popup uses its OWN modal element, not the form popup."""
        html = _read(INDEX_HTML)
        assert 'id="reservationViewModal"' in html
        assert 'id="reservationViewModalBody"' in html
        assert 'id="reservationViewModalFooter"' in html

    def test_popup_does_not_reference_form_modal(self):
        """AC10 — the reservation popup never touches the shared form modal."""
        src = _strip_js_comments(_read(RESERVATION_POPUP))
        assert "formModal" not in src, (
            "Reservation popup must not reference the form modal — US-007 AC10"
        )
