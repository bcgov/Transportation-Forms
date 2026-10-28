"""Source contracts for fresh Form Insights requests and local refresh labels."""

from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (FRONTEND / path).read_text(encoding="utf-8")


def test_refresh_is_accessible_and_uses_fresh_read_for_selected_period():
    js = source("js/views/form-insights.js")
    assert 'id="formInsightsRefresh"' in js
    assert 'class="fas fa-arrows-rotate" aria-hidden="true"' in js
    assert "requestPeriod(selectedPeriod, true)" in js
    assert "if (refresh) url.searchParams.set('refresh', 'true')" in js
    assert "refreshButton.disabled = true" in js
    assert "if (ticket === generation) refreshButton.disabled = false" in js
    assert "if (event.target.id === 'formInsightsRetry') void requestPeriod(selectedPeriod, retryRefresh)" in js


def test_last_refresh_appears_only_on_success_and_uses_local_time():
    js = source("js/views/form-insights.js")
    css = source("css/main.css")
    assert "const refreshedAt = refresh ? receivedAt : null" in js
    assert "formatDateTime(refreshedAt.toISOString())" in js
    assert 'id="formInsightsLastRefresh"' in js
    assert "refreshTime.hidden = !refreshedAt" in js
    assert "lastRefreshAt = refreshedAt" in js
    assert "showResult(lastSuccess, lastRefreshAt, lastSuccessAt)" in js
    assert "lastRefreshAt = null" in js
    assert "refreshTime.textContent = ''" not in js
    assert ".form-insights__refresh" in css
    assert "align-items: flex-end;" in css.split(".form-insights__refresh", 1)[1].split("}", 1)[0]
    assert "#formInsightsThrough" not in js
