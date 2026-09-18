"""Redaction regression tests.

The masked-key case below is not hypothetical: a provider returned
``gsk_ABCD****...****WXYZ`` in a 401 body during development, and the original
patterns let the visible head and tail through into an error message bound for
the response body.
"""

from __future__ import annotations

import pytest

from app.observability import RequestTrace, redact


@pytest.mark.parametrize(
    "text, leaked",
    [
        (
            "Incorrect API key provided: gsk_O3gW****************3mBf. See docs.",
            ["gsk_O3gW", "3mBf"],
        ),
        ("Authorization: Bearer gsk_livekeymaterial1234567890", ["gsk_live", "1234567890"]),
        ("api_key=sk-proj-abcdefghijklmnopqrst", ["sk-proj", "abcdefghij"]),
        ("token: AIzaSyD_ExampleLooking_Key_000111222", ["AIzaSyD"]),
    ],
)
def test_credential_material_never_survives_redaction(text, leaked):
    cleaned = redact(text)
    for fragment in leaked:
        assert fragment not in cleaned, f"{fragment!r} leaked through redaction"


def test_ordinary_error_text_is_preserved():
    assert "connection refused" in redact("connection refused to host")


def test_detail_is_length_clamped():
    assert len(redact("x " * 5000)) <= 210


def test_trace_dict_contains_no_free_text():
    trace = RequestTrace(scenario_id="GRID-101")
    with trace.stage("interpret"):
        pass
    payload = trace.as_dict()
    assert payload["scenario_id"] == "GRID-101"
    assert "interpret_ms" in payload
    assert all(not isinstance(v, str) or len(v) < 100 for v in payload.values() if v is not None)
