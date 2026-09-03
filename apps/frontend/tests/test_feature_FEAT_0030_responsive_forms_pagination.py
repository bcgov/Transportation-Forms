"""Source-contract coverage for FEAT-0030 US-006 Forms pagination."""

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_pagination_uses_approved_semantic_composition():
    html = _source("index.html")
    pagination_start = html.split('<div class="forms-pagination"', maxsplit=1)[1]
    pagination = pagination_start.split("</section>", maxsplit=1)[0]
    previous_icon = '<i class="fas fa-arrow-left" aria-hidden="true"></i>Previous'
    next_icon = 'Next<i class="fas fa-arrow-right" aria-hidden="true"></i>'

    assert 'id="paginationSummary"' in pagination
    assert 'role="group" aria-label="Pagination"' in pagination
    assert 'id="prevPageBtn" type="button"' in pagination
    assert 'aria-label="Previous page"' in pagination
    assert previous_icon in pagination
    assert 'id="nextPageBtn" type="button"' in pagination
    assert 'aria-label="Next page"' in pagination
    assert next_icon in pagination


def test_pagination_uses_confirmed_offset_limit_and_total():
    forms_js = _source("js/views/forms-list.js")
    load_signature = "export async function loadForms(requestedSkip = _currentSkip)"

    assert load_signature in forms_js
    assert "params.set('skip', String(candidateSkip))" in forms_js
    assert "params.set('limit', String(_currentLimit))" in forms_js
    assert "_currentSkip = candidateSkip;" in forms_js
    assert "_lastListTotal = data.total;" in forms_js
    assert "Math.min(_currentSkip + _currentLimit, total)" in forms_js
    assert "prevBtn.disabled = _currentSkip <= 0;" in forms_js
    assert "nextBtn.disabled = _currentSkip + _currentLimit >= total;" in forms_js


def test_page_navigation_is_guarded_and_commits_only_after_success():
    forms_js = _source("js/views/forms-list.js")
    pending_previous_guard = (
        "if (_isFormsRequestPending || _currentSkip <= 0) " "return;"
    )

    assert "let _isFormsRequestPending = false;" in forms_js
    assert "_setPaginationPending();" in forms_js
    assert pending_previous_guard in forms_js
    assert "loadForms(Math.max(0, _currentSkip - _currentLimit));" in forms_js
    assert (
        "if (_isFormsRequestPending || "
        "_currentSkip + _currentLimit >= _lastListTotal) return;"
    ) in forms_js
    assert "loadForms(_currentSkip + _currentLimit);" in forms_js
    assert "_currentSkip += _currentLimit;" not in forms_js


def test_loading_and_failure_disable_unconfirmed_navigation():
    forms_js = _source("js/views/forms-list.js")
    busy_state = "paginationContainer?.setAttribute('aria-busy', 'true');"

    assert "function _setPaginationPending()" in forms_js
    assert busy_state in forms_js
    assert "if (prevBtn) prevBtn.disabled = true;" in forms_js
    assert "if (nextBtn) nextBtn.disabled = true;" in forms_js
    assert "paginationContainer.removeAttribute('aria-busy');" in forms_js
    assert "_currentSkip = 0;" in forms_js
    assert "_updatePaginationControls(0);" in forms_js
    assert "Unable to load forms. Please try again." in forms_js


def test_malformed_or_inconsistent_pages_fail_closed():
    forms_js = _source("js/views/forms-list.js")

    assert "function _isValidFormsPage(data, requestedSkip, usableItemCount)" in forms_js
    assert "Number.isSafeInteger(data?.total)" in forms_js
    assert "data.total < 0" in forms_js
    assert "!Array.isArray(data.items)" in forms_js
    assert "data.skip !== requestedSkip" in forms_js
    assert "data.limit !== _currentLimit" in forms_js
    assert "data.items.length !== expectedItems" in forms_js
    assert "usableItemCount !== expectedItems" in forms_js
    assert "data.total === 0 ? requestedSkip === 0 : requestedSkip < data.total" in forms_js
    assert "throw new Error('Invalid Forms response');" in forms_js


def test_discovery_and_page_size_changes_keep_first_page_reset():
    forms_js = _source("js/views/forms-list.js")
    allowed_sizes = "const ALLOWED_PAGE_SIZES = new Set([24, 48, 96]);"

    assert allowed_sizes in forms_js
    assert "let _currentLimit = 24;" in forms_js
    assert "pageSize.value = '24';" in forms_js
    assert "? requestedLimit : 24;" in forms_js
    assert "function _onPageSizeChange()" in forms_js
    assert "export function searchForms()" in forms_js
    assert "export function applyFilters()" in forms_js
    assert forms_js.count("_currentSkip = 0;") >= 4


def test_mobile_pagination_switches_at_620_pixels():
    css = _source("css/main.css")
    mobile_rules = css.split("@media (max-width: 620px)", maxsplit=1)[1].split(
        "@media (max-width: 575.98px)", maxsplit=1
    )[0]

    assert ".forms-pagination > span" in mobile_rules
    assert "display: none;" in mobile_rules
    assert ".forms-pagination__actions" in mobile_rules
    assert "width: 100%;" in mobile_rules
    assert ".forms-pagination .forms-command-button" in mobile_rules
    assert "flex: 1;" in mobile_rules


def test_pagination_retains_visible_focus_and_native_disabled_buttons():
    html = _source("index.html")
    css = _source("css/main.css")
    pagination_start = html.split('<div class="forms-pagination"', maxsplit=1)[1]
    pagination = pagination_start.split("</section>", maxsplit=1)[0]

    assert ".forms-command-button:focus-visible" in css
    assert ".forms-command-button:not(:disabled):hover" in css
    disabled_rules = css.split(".forms-command-button:disabled", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    assert "cursor: not-allowed;" in disabled_rules
    assert "background: #f6f7f9;" in disabled_rules
    assert "color: #98a2b3;" in disabled_rules
    assert "box-shadow: none;" in disabled_rules
    assert 'id="prevPageBtn" type="button"' in html
    assert 'id="nextPageBtn" type="button"' in html
    assert 'aria-disabled="true"' not in pagination
