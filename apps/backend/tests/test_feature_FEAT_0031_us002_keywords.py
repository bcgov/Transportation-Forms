"""FEAT-0031 US-002 keyword validation at the form-write boundary."""

import pytest
from pydantic import ValidationError

from backend.routes.forms import FormCreateRequest, FormUpdateRequest


def _request(model, keywords):
    if model is FormCreateRequest:
        return model(
            title="Keyword test", description="Keyword test", keywords=keywords
        )
    return model(keywords=keywords)


@pytest.mark.parametrize("model", [FormCreateRequest, FormUpdateRequest])
def test_valid_keywords_are_trimmed_and_keep_original_case(model):
    request = _request(
        model, ["  Truck  ", "a" * 50, "Caf\u00e9 & routes", "\U0001f680" * 50]
    )

    assert request.keywords == [
        "Truck",
        "a" * 50,
        "Caf\u00e9 & routes",
        "\U0001f680" * 50,
    ]


@pytest.mark.parametrize("model", [FormCreateRequest, FormUpdateRequest])
@pytest.mark.parametrize(
    "keywords",
    [
        ["   "],
        ["a" * 51],
        ["\U0001f680" * 51],
        ["a\x00b"],
        ["a\x85b"],
        ["\x85Truck"],
        ["\x1cTruck"],
        ["a\nb"],
        ["Truck", " truck "],
    ],
)
def test_invalid_keywords_are_rejected_at_write_boundary(model, keywords):
    with pytest.raises(ValidationError):
        _request(model, keywords)


@pytest.mark.parametrize("model", [FormCreateRequest, FormUpdateRequest])
def test_optional_keywords_remain_optional(model):
    assert _request(model, None).keywords is None
