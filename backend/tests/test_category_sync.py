"""The frontend's category list must equal the backend taxonomy's.

They drifted three ways on Ashborne Silicon (query.ts, corpus.ts and snapshot.py
each had their own hidden-category set), and the filter counts disagreed with
what the list showed. Volt keeps one list per side and this test ties them.
"""

import re
from pathlib import Path

from backend.app import taxonomy as tx
from backend.app.snapshot import HIDDEN_CATEGORIES

TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "categories.ts"


def _ts_list(name: str) -> list[str]:
    src = TS.read_text(encoding="utf-8")
    m = re.search(name + r"[^=]*=\s*(?:new Set<string>\()?\[(.*?)\]", src, re.S)
    assert m, f"{name} not found in categories.ts"
    return re.findall(r"'([^']+)'", m.group(1))


def test_categories_match():
    assert _ts_list("CATEGORIES") == list(tx.CATEGORIES)


def test_hidden_categories_match():
    assert set(_ts_list("HIDDEN_CATEGORIES")) == set(HIDDEN_CATEGORIES)


def test_requirement_tags_match():
    assert _ts_list("REQUIREMENT_TAGS") == list(tx.REQUIREMENT_TAGS)


def test_blurbs_cover_every_category():
    src = TS.read_text(encoding="utf-8")
    for cat in tx.CATEGORIES:
        assert f"'{cat}':" in src, cat
        assert tx.CATEGORY_BLURBS[cat]
