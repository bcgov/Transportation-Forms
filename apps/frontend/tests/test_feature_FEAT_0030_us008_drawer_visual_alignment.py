"""Visual-alignment contracts for the FEAT-0030 US-008 details drawer."""

from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_drawer_tracks_the_normal_flow_header_for_every_authorized_layout() -> None:
    sidebar = _source("js/sidebar.js")
    css = _source("css/main.css")

    sync = sidebar.split("function _syncSidebarTop()", maxsplit=1)[1].split(
        "function _scheduleSidebarTopSync()", maxsplit=1
    )[0]
    schedule = sidebar.split("function _scheduleSidebarTopSync()", maxsplit=1)[1].split(
        "function _render()", maxsplit=1
    )[0]

    assert "if (!_available || !_header) return;" not in sync
    assert "if (!_available || _sidebarTopFrame !== null) return;" not in schedule
    assert "removeProperty('--staff-sidebar-top')" not in sidebar
    assert "top: var(--staff-sidebar-top);" in css
    assert "inset: var(--staff-sidebar-top) 0 0 0;" in css


def test_drawer_metadata_uses_site_type_and_mockup_row_separators() -> None:
    css = _source("css/main.css")

    assert ".form-details-drawer {" in css
    assert "font-family: inherit;" in css
    assert "grid-template-columns: 7.5rem minmax(0, 1fr);" in css
    assert "border-top: 1px solid #d0d5dd;" in css
    assert "padding: 0.8125rem 0;" in css
    assert "border-bottom: 1px solid #d0d5dd;" in css
    assert "font-size: 0.8125rem;" in css


def test_drawer_status_reuses_card_badge_and_clears_canonical_state() -> None:
    html = _source("index.html")
    drawer = _source("js/shared/form-details-drawer.js")

    assert 'class="forms-result-card__status" id="formDetailsStatus"' in html
    assert "elements.status.dataset.status = _getStatusStyle(form.status);" in drawer
    assert "delete elements.status.dataset.status;" in drawer
    assert "form-details-drawer__status" not in html
    assert ".form-details-drawer__status" not in _source("css/main.css")