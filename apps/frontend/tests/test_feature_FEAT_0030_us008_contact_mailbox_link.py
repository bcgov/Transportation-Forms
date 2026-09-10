"""Source contract for the FEAT-0030 US-008 contact mailbox link."""

from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1]
DRAWER_PATH = FRONTEND_DIR / "js" / "shared" / "form-details-drawer.js"


def test_contact_mailbox_uses_safe_mailto_link() -> None:
    drawer = DRAWER_PATH.read_text(encoding="utf-8")
    contact_renderer = drawer.split(
        "function _renderContactNote", maxsplit=1
    )[1]
    renderer = contact_renderer.split("\n}", maxsplit=1)[0]

    assert "encodeURIComponent(mailbox).replace(/%40/g, '@')" in renderer
    assert ".replace('%40', '@')" not in renderer
    assert "mailboxLink.href = `mailto:${encodedMailbox}`" in renderer
    assert "mailboxLink.textContent = mailbox" in renderer
    assert "elements.contactNoteText.append(" in renderer
    assert "innerHTML" not in renderer
