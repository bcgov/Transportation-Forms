"""Source contracts for FEAT-0030 protected modal fail-closed cleanup."""

from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_protected_modals_force_closed_state_on_lifecycle_reset() -> None:
    for relative_path in (
        "js/shared/form-view-popup.js",
        "js/shared/reservation-view-popup.js",
    ):
        popup = _source(relative_path)
        hide_modal = popup.split("function _hideModal()", maxsplit=1)[1].split(
            "function _resetPopupLifecycle()", maxsplit=1
        )[0]

        assert "inst.hide()" in hide_modal
        assert "document.activeElement.blur()" in hide_modal
        assert "modalEl.classList.remove('show')" in hide_modal
        assert "modalEl.style.display = 'none'" in hide_modal
        assert "modalEl.setAttribute('aria-hidden', 'true')" in hide_modal
        assert "modalEl.removeAttribute('aria-modal')" in hide_modal
        assert "modalEl.removeAttribute('role')" in hide_modal
        assert "if (!document.querySelector('.modal.show'))" in hide_modal
        assert "document.body.classList.remove('modal-open')" in hide_modal
        assert "backdrop.remove()" in hide_modal