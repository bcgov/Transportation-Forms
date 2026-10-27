"""Source contracts for FEAT-0031 US-011 Form Insights presentation.

The frontend test suite uses pytest source contracts; these checks do not
execute JavaScript or require a browser or Node.js.
"""

import re
from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (FRONTEND / path).read_text(encoding="utf-8")


def entries(js: str, name: str) -> list[tuple[str, ...]]:
    declaration = re.search(rf"const {name} = \[(.*?)\];", js, re.DOTALL)
    assert declaration, f"{name} must have an explicit allowlist"
    return re.findall(r"\['([^']+)', '([^']+)'(?:, (\d+|null))?\]", declaration.group(1))


def test_insights_and_audit_mount_independently_after_edit_form_load():
    html = source("index.html")
    form = source("js/views/forms-create.js")
    insights = source("js/views/form-insights.js")
    audit = source("js/views/form-audit-history.js")
    edit = form.split("async function _loadFormForEdit(formId)", 1)[1].split(
        "function _validatedFormData()", 1
    )[0]

    assert html.count('id="formInsightsMount"') == 1
    assert html.count('id="auditHistoryMount"') == 1
    assert html.index('id="formInsightsMount"') < html.index('id="auditHistoryMount"')
    assert "Form Insights" not in html
    assert "Audit History" not in html
    assert "clearFormInsights();" in form.split("export function resetFormState()", 1)[1]
    assert "clearAuditHistory();" in form.split("export function resetFormState()", 1)[1]
    assert edit.index("if (!response.ok) throw") < edit.index("const form = await response.json()")
    assert edit.index("const form = await response.json()") < edit.index("loadFormInsights(formId);")
    assert "loadAuditHistory(formId);" in edit
    assert "loadFormInsights(" not in form.split("export async function showCreateView()", 1)[1].split(
        "export async function showEditView", 1
    )[0]
    assert "hasPermission('form:stats')" in insights
    assert "hasPermission('form:audit')" in audit


def test_missing_stats_permission_prevents_markup_and_network_request():
    js = source("js/views/form-insights.js")
    load = js.split("export function loadFormInsights(id)", 1)[1]
    gate = "if (!hasPermission('form:stats') || !hasPermission('form:edit')) return;"

    assert gate in load
    assert load.index(gate) < load.index("host.innerHTML")
    assert load.index(gate) < load.index("requestPeriod('30d')")
    assert "mount()?.replaceChildren()" in js.split("export function clearFormInsights()", 1)[1]
    assert "window.addEventListener('auth:session-cleared', clearFormInsights)" in js


def test_periods_are_allowlisted_and_every_new_edit_defaults_to_30_days():
    js = source("js/views/form-insights.js")
    assert entries(js, "PERIODS") == [
        ("1d", "1 day", "1"),
        ("7d", "7 days", "7"),
        ("30d", "30 days", "30"),
        ("90d", "90 days", "90"),
        ("180d", "180 days", "180"),
        ("1y", "1 year", "365"),
        ("all", "All time", "null"),
    ]
    assert "let selectedPeriod = '30d'" in js
    assert "selectedPeriod = '30d'" in js.split("export function clearFormInsights()", 1)[1]
    assert "void requestPeriod('30d')" in js
    assert 'aria-pressed="${period === \'30d\'}"' in js
    assert "button.dataset.insightsPeriod === selectedPeriod" in js
    assert "button.dataset.insightsPeriod !== selectedPeriod" in js
    assert js.count("void requestPeriod(button.dataset.insightsPeriod)") == 1
    assert "url.searchParams.set('period', period)" in js
    assert "localStorage" not in js
    assert "sessionStorage" not in js


def test_exactly_six_safe_totals_are_mapped_from_current_response():
    js = source("js/views/form-insights.js")
    assert entries(js, "METRICS") == [
        ("download", "Form downloads", ""),
        ("link_click", "Source-link clicks", ""),
        ("detail_view", "Form-detail views", ""),
    ]
    assert entries(js, "SOURCES") == [
        ("Staff", "Staff portal", ""),
        ("Public", "Public portal", ""),
    ]
    assert 'data-insights-value="${metric}-${source}"' in js
    assert "result.totals?.[metric]?.[source]" in js
    assert "Number.isSafeInteger(value)" in js
    assert "value < 0" in js
    assert "result.totals[metric][source].toLocaleString('en-CA')" in js
    assert "result.period !== period" in js
    assert "innerHTML = result" not in js
    assert "collection_start" not in js
    assert "completeness" not in js.lower()


def test_caption_and_data_through_derive_from_each_response_cutoff():
    js = source("js/views/form-insights.js")
    dates = js.split("function displayDates(result, receivedAt)", 1)[1].split(
        "function updateSelection()", 1
    )[0]

    assert "result.pct_day_cutoff" in dates
    assert "through.setUTCDate(through.getUTCDate() - 1)" in dates
    assert "result.data_through !== through.toISOString().slice(0, 10)" in dates
    assert "start.setUTCDate(start.getUTCDate() - days)" in dates
    assert "All time retained totals through" in dates
    assert "through ${dateLabel(through)} (PCT)" in dates
    assert "dateLabel(start)" in dates
    assert "timeZone: 'UTC'" in js
    assert "mount().querySelector('#formInsightsCaption').textContent = dates.caption" in js
    assert 'id="formInsightsThrough"' not in js


def test_loading_errors_and_unavailable_are_distinct_and_recoverable():
    js = source("js/views/form-insights.js")
    request = js.split("async function requestPeriod(period, refresh = false)", 1)[1].split(
        "export function clearFormInsights()", 1
    )[0]

    assert request.index("clearValues();") < request.index("await fetch(")
    assert "showState('Loading form activity...')" in request
    assert "status === 404 ? 'Form activity is unavailable.' : 'Unable to load form activity.'" in request
    assert "error.status !== 404" in request
    assert "if (ticket !== generation) return" in request.split("catch (error)", 1)[1]
    assert "clearValues();" in request.split("catch (error)", 1)[1]
    assert 'id="formInsightsStatus" role="status" aria-live="polite"' in js
    assert 'id="formInsightsError" role="alert"' in js
    assert 'id="formInsightsRetry"' in js
    assert "if (event.target.id === 'formInsightsRetry') void requestPeriod(selectedPeriod, retryRefresh)" in js


def test_revoked_stats_permission_reverts_to_last_success_without_stale_races():
    js = source("js/views/form-insights.js")
    request = js.split("async function requestPeriod(period, refresh = false)", 1)[1].split(
        "export function clearFormInsights()", 1
    )[0]

    assert "const ticket = ++generation" in request
    assert request.count("if (ticket !== generation) return") >= 3
    assert request.index("await fetch(") < request.index("if (ticket !== generation) return")
    assert "const result = await response.json()" in request
    assert "if (result.period !== period)" in request
    assert "lastSuccess = result" in request
    denial = request.split("if (error.status === 403 && lastSuccess && lastSuccess.period !== period)", 1)[1].split(
        "} else {", 1
    )[0]
    assert "selectedPeriod = lastSuccess.period" in denial
    assert "updateSelection()" in denial
    assert "showResult(lastSuccess, lastRefreshAt, lastSuccessAt)" in denial
    assert "showNotification('You do not have permission to view statistics.', 'danger')" in denial
    assert "lastSuccess = null" in js.split("export function clearFormInsights()", 1)[1]


def test_keyboard_semantics_and_small_screen_readability():
    js = source("js/views/form-insights.js")
    css = source("css/main.css")

    assert '<button type="button" data-insights-period=' in js
    assert 'role="group" aria-label="Statistics time scale"' in js
    assert 'aria-pressed="${period === \'30d\'}"' in js
    assert '<th scope="col">' in js
    assert '<th scope="row">${label}</th>' in js
    assert "SOURCES.map(([source, label])" in js
    assert "#createView :focus-visible" in css
    assert ".form-insights__periods button[aria-pressed=\"true\"]" in css
    assert ".form-insights__table-wrap" in css
    assert "overflow-x: auto;" in css.split(".form-insights__table-wrap", 1)[1].split("}", 1)[0]
    assert ".form-insights__table { min-width: 0; table-layout: fixed; }" in css
