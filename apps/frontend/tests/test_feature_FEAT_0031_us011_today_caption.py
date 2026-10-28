"""Source contract for partial-day Form Insights captions."""

from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1]


def test_today_caption_uses_the_current_response_and_its_receipt_time():
    js = (FRONTEND / "js/views/form-insights.js").read_text(encoding="utf-8")
    assert "result.data_through !== through.toISOString().slice(0, 10)" in js
    assert "if (result.period === '1d')" in js
    caption = next(
        line.strip()
        for line in js.splitlines()
        if line.strip().startswith("caption: `Today so far")
    )
    assert caption == (
        "caption: `Today so far (${dateLabel(through)} PCT; as of "
        "${formatDateTime(receivedAt.toISOString())} local time)`,"
    )
    assert "const receivedAt = new Date()" in js
    assert "showResult(result, refreshedAt, receivedAt)" in js
    assert "showResult(lastSuccess, lastRefreshAt, lastSuccessAt)" in js
    assert "lastSuccessAt = null" in js
