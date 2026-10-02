"""Tests for HTML description cleaning utilities."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.app.description_cleaner import (
    clean_html_description,
    decode_html_entities,
    normalize_whitespace,
    strip_tags,
    truncate_description_cleanly,
)


def test_strip_basic_tags():
    assert strip_tags("<p>Hello</p>") == " Hello "


def test_strip_nested_tags():
    result = strip_tags("<div><p><strong>RTL</strong> Design</p></div>")
    assert "RTL" in result
    assert "Design" in result
    assert "<" not in result


def test_decode_lt_gt():
    result = decode_html_entities("&lt;br&gt;")
    assert result == "<br>"
    result2 = decode_html_entities("&lt;p&gt;Hello&lt;/p&gt;")
    assert result2 == "<p>Hello</p>"


def test_decode_amp():
    assert "&" == decode_html_entities("&amp;")


def test_decode_apostrophe():
    assert "'" in decode_html_entities("&#x27;")


def test_normalize_collapse_spaces():
    result = normalize_whitespace("Hello   World")
    assert result == "Hello World"


def test_normalize_collapse_newlines():
    result = normalize_whitespace("Hello\n\n\n\nWorld")
    assert result == "Hello\n\nWorld"


def test_clean_html_full_pipeline():
    raw = "<p>We are looking for a &lt;strong&gt;Design Verification&lt;/strong&gt; engineer.</p>"
    result = clean_html_description(raw)
    assert "Design Verification" in result
    assert "<" not in result
    assert "&lt;" not in result


def test_clean_html_strips_br_entities():
    raw = "Required skills:&lt;br&gt;- UVM&lt;br&gt;- SystemVerilog"
    result = clean_html_description(raw)
    assert "UVM" in result
    assert "&lt;" not in result


def test_clean_html_empty_input():
    assert clean_html_description("") == ""
    assert clean_html_description(None) == ""  # type: ignore[arg-type]


def test_clean_html_truncation():
    long_text = "A " * 3000
    result = clean_html_description(long_text, max_length=100)
    assert len(result) <= 110  # some slack for the ellipsis
    assert result.endswith("…")


def test_truncate_description_cleanly():
    text = "Hello world " * 100
    result = truncate_description_cleanly(text, length=50)
    assert len(result) <= 60
    assert result.endswith("…")


def test_clean_html_real_workday_snippet():
    raw = (
        "&lt;p&gt;NVIDIA is looking for a Design Verification Engineer.&lt;/p&gt;"
        "&lt;ul&gt;&lt;li&gt;UVM testbench development&lt;/li&gt;"
        "&lt;li&gt;SystemVerilog&lt;/li&gt;&lt;/ul&gt;"
    )
    result = clean_html_description(raw)
    assert "UVM testbench development" in result
    assert "SystemVerilog" in result
    assert "&lt;" not in result
    assert "<" not in result
