"""FEAT-0002: Unit tests for MIME-to-file-type mapping logic.

Covers BR-001 (mapping table), BR-002 (storage format), and edge cases
such as missing, empty, and case-insensitive MIME types.
"""

import pytest

from backend.services.s3_service import derive_file_type, MIME_TYPE_MAP


# ── TC1.1–TC1.7: Known MIME types map correctly ──────────────────────────────


@pytest.mark.unit
class TestKnownMimeTypes:
    """All MIME types in the BR-001 mapping table produce the correct label."""

    @pytest.mark.parametrize(
        "mime, expected",
        [
            ("application/pdf", "pdf"),
            ("application/msword", "doc"),
            (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "docx",
            ),
            ("application/vnd.ms-excel", "xls"),
            (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "xlsx",
            ),
            ("text/csv", "csv"),
            ("image/jpeg", "jpg"),
            ("image/png", "png"),
            ("image/gif", "gif"),
            ("image/webp", "webp"),
            ("application/zip", "zip"),
        ],
    )
    def test_known_mime_type(self, mime, expected):
        assert derive_file_type(mime) == expected


# ── TC1.8–TC1.9: Unknown / missing MIME types ────────────────────────────────


@pytest.mark.unit
class TestUnknownMimeTypes:
    """Unknown, missing, or absent MIME types yield 'unknown'."""

    def test_unrecognized_mime(self):
        """TC1.8: Proprietary MIME type → 'unknown'."""
        assert derive_file_type("application/x-custom-proprietary") == "unknown"

    def test_octet_stream_fallback(self):
        """TC1.9: application/octet-stream (browser default) → 'unknown'."""
        assert derive_file_type("application/octet-stream") == "unknown"

    def test_empty_string(self):
        assert derive_file_type("") == "unknown"

    def test_none_value(self):
        assert derive_file_type(None) == "unknown"


# ── TC1.17: Case normalization ────────────────────────────────────────────────


@pytest.mark.unit
class TestMimeCaseHandling:
    """MIME types are matched case-insensitively per RFC 2045."""

    def test_uppercase_mime(self):
        assert derive_file_type("APPLICATION/PDF") == "pdf"

    def test_mixed_case_mime(self):
        assert derive_file_type("Image/PNG") == "png"


# ── Edge cases ────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestMimeEdgeCases:
    """Edge cases: MIME with parameters, whitespace, etc."""

    def test_mime_with_charset_parameter(self):
        """Content-Type often includes '; charset=utf-8' — must be stripped."""
        assert derive_file_type("text/csv; charset=utf-8") == "csv"

    def test_mime_with_leading_whitespace(self):
        assert derive_file_type("  application/pdf  ") == "pdf"

    def test_mime_type_map_has_expected_count(self):
        """Sanity check that the map covers exactly the 11 entries from BR-001."""
        assert len(MIME_TYPE_MAP) == 11

    def test_all_values_are_lowercase(self):
        """BR-005: All stored values must be lowercase."""
        for value in MIME_TYPE_MAP.values():
            assert value == value.lower()
            assert not value.startswith(".")
