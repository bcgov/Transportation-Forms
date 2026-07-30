"""FEAT-0026 US-016 — Canonical HTML sanitizer for CMS body content.

This module is the single allow-listed configuration of the ``nh3``
(Rust-backed Ammonia) HTML sanitizer used by the mini-CMS.  Every code path
that persists or renders user-authored HTML for a CMS page MUST go through
:func:`sanitize_html`.  Centralizing the config eliminates configuration
drift and gives security review one file to audit.

Design references:

* US-016 — XSS sanitization policy (allow-listed tags/attrs/styles).
* US-001 — Create page service that calls this sanitizer before persisting.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, FrozenSet, Optional, Set

import nh3

# ---------------------------------------------------------------------------
# Allow-lists (US-016 AC1, AC3)
# ---------------------------------------------------------------------------

# Block-level + inline + media tags permitted in body_html.
_ALLOWED_TAGS: Set[str] = {
    # Block
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "hr",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "figure",
    "figcaption",
    "div",
    # Inline
    "a",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "code",
    "pre",
    "br",
    "span",
    "abbr",
    "sub",
    "sup",
    "mark",
    "kbd",
}

# Tags whose entire subtree must be removed (text content discarded).  nh3
# default already strips ``script``/``style`` content; listing them here is
# defense in depth in case the default behavior changes.
_CLEAN_CONTENT_TAGS: Set[str] = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "form",
    "input",
    "textarea",
    "button",
    "select",
    "option",
    "svg",
    "math",
    "noscript",
}

# Per-tag allow-listed attributes (US-016 AC3).  ``id`` is handled via the
# attribute_filter to enforce a strict ID format.  ``rel`` on <a> is
# omitted because nh3 manages it via ``link_rel`` and rejects per-tag
# entries when that option is set.
_ALLOWED_ATTRIBUTES: Dict[str, Set[str]] = {
    "a": {"href", "title"},
    "table": {"class"},
    "th": {"colspan", "rowspan", "scope"},
    "td": {"colspan", "rowspan"},
    "span": {"class"},
    "div": {"class"},
    "code": {"class"},
    "pre": {"class"},
    # Tags that may carry only the global attrs handled below
    "blockquote": set(),
    "abbr": {"title"},
}

# URL schemes allowed in href / src style attributes.  Note: nh3 also
# permits scheme-relative URLs ("//evil.com/...") by default; we strip those
# in the attribute_filter (US-016 AC5).
_ALLOWED_URL_SCHEMES: Set[str] = {"http", "https", "mailto", "tel"}

# CSS properties permitted in ``style`` attributes (US-016 AC4).
_ALLOWED_CSS_PROPERTIES: FrozenSet[str] = frozenset(
    {
        "color",
        "background-color",
        "text-align",
        "font-style",
        "font-weight",
        "text-decoration",
        "vertical-align",
        "list-style-type",
    }
)

# Tokens that must never appear inside a style attribute value.  Matched
# case-insensitively after lowercasing the value.
_FORBIDDEN_STYLE_TOKENS = (
    "url(",
    "expression(",
    "javascript:",
    "vbscript:",
    "data:",
    "@import",
    "var(",
    "calc(",
    "behavior:",
    "binding:",
    "-moz-binding",
)

# Slug used for ID attributes (lowercase alphanumerics + hyphens, 1-64 chars).
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# Allowed class tokens (alphanumerics, hyphens, underscores).
_CLASS_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Bidi-override + zero-width characters that have no legitimate use inside
# admin-authored content but can defeat reviewer inspection (US-016 AC6).
_FORBIDDEN_UNICODE_CHARS = (
    "\u202a",  # LRE
    "\u202b",  # RLE
    "\u202c",  # PDF
    "\u202d",  # LRO
    "\u202e",  # RLO
    "\u2066",  # LRI
    "\u2067",  # RLI
    "\u2068",  # FSI
    "\u2069",  # PDI
    "\u200e",  # LRM
    "\u200f",  # RLM
)
_UNICODE_STRIP_RE = re.compile(
    "[" + "".join(re.escape(c) for c in _FORBIDDEN_UNICODE_CHARS) + "]"
)


def _value_is_safe_url(value: str) -> bool:
    """Return True when ``value`` is a URL we are willing to emit.

    Allows relative URLs (no scheme, no host) but rejects scheme-relative
    URLs (``//evil.com/...``) because they bypass scheme allow-listing.
    """
    if value is None:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    # Block scheme-relative URLs explicitly (US-016 AC5).
    if stripped.startswith("//"):
        return False
    # Reject control / whitespace characters embedded in the URL.
    if any(ord(ch) < 0x20 for ch in stripped):
        return False
    # If a scheme is present it must be in the allow-list.
    if ":" in stripped:
        scheme, _, _ = stripped.partition(":")
        scheme = scheme.strip().lower()
        # Detect schemes embedded with whitespace like " javas\tcript:..."
        if scheme not in _ALLOWED_URL_SCHEMES:
            return False
    return True


def _sanitize_style_value(raw: str) -> Optional[str]:
    """Return a cleaned style attribute value or None to drop the attr."""
    if not raw:
        return None
    lowered = raw.lower()
    for token in _FORBIDDEN_STYLE_TOKENS:
        if token in lowered:
            return None

    safe_declarations = []
    for declaration in raw.split(";"):
        if ":" not in declaration:
            continue
        prop, _, value = declaration.partition(":")
        prop = prop.strip().lower()
        value = value.strip()
        if prop not in _ALLOWED_CSS_PROPERTIES:
            continue
        if not value:
            continue
        # Block any residual angle-bracket content as a defense in depth
        # against CSS-based HTML smuggling.
        if "<" in value or ">" in value:
            continue
        safe_declarations.append(f"{prop}: {value}")

    if not safe_declarations:
        return None
    return "; ".join(safe_declarations)


def _sanitize_class_value(raw: str) -> Optional[str]:
    """Return a cleaned class attribute or None when nothing survives."""
    if not raw:
        return None
    tokens = [tok for tok in raw.split() if _CLASS_TOKEN_RE.match(tok)]
    if not tokens:
        return None
    return " ".join(tokens)


def _attribute_filter(
    element: str, attribute: str, value: str
) -> Optional[str]:
    """nh3 attribute filter callback — drop or transform attributes.

    Returning ``None`` removes the attribute entirely; returning a string
    keeps it with the (possibly cleaned) value.  This runs AFTER nh3's
    per-tag attribute allow-list, so we only need to enforce the
    value-level rules here.
    """
    attr = attribute.lower()
    elem = element.lower()

    # Global ``id`` — restrict format and drop unknown patterns.
    if attr == "id":
        return value if _ID_RE.match(value or "") else None

    if attr == "class":
        return _sanitize_class_value(value)

    if attr == "style":
        # We did not allow ``style`` in the per-tag map, but defense in depth
        # if a future config change adds it.
        return _sanitize_style_value(value)

    # ``data-*`` attributes — only data-cms-* allowed (US-016 AC8).
    if attr.startswith("data-"):
        if not attr.startswith("data-cms-"):
            return None
        # Keep value but strip dangerous Unicode characters.
        return _UNICODE_STRIP_RE.sub("", value or "")

    # ``href`` / ``src`` style values — enforce scheme allow-list.
    if attr in {"href", "src", "cite", "action"}:
        return value if _value_is_safe_url(value) else None

    # ``width`` / ``height`` — numeric only.
    if attr in {"width", "height", "colspan", "rowspan"}:
        return value if value.isdigit() and 1 <= len(value) <= 4 else None

    # ``scope`` on <th>.
    if attr == "scope" and elem == "th":
        return value if value in {"row", "col", "rowgroup", "colgroup"} else None

    # ``title`` / ``alt`` — strip unicode bidi but otherwise allow.
    if attr in {"title", "alt"}:
        return _UNICODE_STRIP_RE.sub("", value or "")

    return value


def sanitize_html(html: Optional[str]) -> str:
    """Sanitize CMS body HTML against the FEAT-0026 US-016 allow-list.

    Always returns a string (empty when ``html`` is None/empty).  The output
    is safe to store in the database and to render directly to authenticated
    or anonymous users.

    Notes:
        * Comments are stripped (``strip_comments=True``).
        * ``script``/``style``/etc. tags have their content discarded.
        * Anchors are rewritten with ``rel="noopener noreferrer"``.
        * Forbidden Unicode bidi/zero-width characters are removed BEFORE
          parsing so they cannot survive in text nodes.
    """
    if not html:
        return ""

    # US-016 AC6 — strip dangerous Unicode characters from the raw text
    # BEFORE handing off to the HTML parser.  We also normalize to NFC to
    # eliminate any pre-composed lookalikes used for confusable spoofing.
    normalized = unicodedata.normalize("NFC", html)
    pre_cleaned = _UNICODE_STRIP_RE.sub("", normalized)

    cleaned = nh3.clean(
        pre_cleaned,
        tags=_ALLOWED_TAGS,
        clean_content_tags=_CLEAN_CONTENT_TAGS,
        attributes={tag: set(attrs) for tag, attrs in _ALLOWED_ATTRIBUTES.items()},
        attribute_filter=_attribute_filter,
        strip_comments=True,
        link_rel="noopener noreferrer",
        url_schemes=_ALLOWED_URL_SCHEMES,
        generic_attribute_prefixes={"data-cms-"},
    )

    return cleaned
