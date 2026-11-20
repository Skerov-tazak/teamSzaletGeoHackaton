"""Run from assistant/:  pytest -q
Requires `python -m rag.ingest` to have been run. Search tests are skipped when Qdrant is down.
"""
from __future__ import annotations

import pytest

from rag import config
from rag.chunker import chunk_doc, load_chunks
from rag.docs import load_docs
from rag.excel_parse import parse_temp
from rag.pdf_parse import load_pages
from rag.toc import load_sections

CORE = ["kukurydza_doradcy", "kukurydza_producenci", "pszenica_doradcy", "pszenica_producenci", "zboza_giorin"]


@pytest.fixture(scope="session")
def chunks():
    if not config.CHUNKS_JSONL.exists():
        pytest.skip("brak chunks.jsonl — uruchom: python -m rag.ingest")
    return load_chunks()


@pytest.fixture(scope="session")
def qdrant_ok():
    from rag.store import QdrantStore, QdrantUnavailable
    try:
        QdrantStore()
    except QdrantUnavailable as e:
        pytest.skip(str(e))
    return True


# ----------------------------------------------------------------------------- chunks
@pytest.mark.parametrize("doc_id", CORE)
def test_each_pdf_has_chunks(chunks, doc_id):
    assert sum(c["doc_id"] == doc_id for c in chunks) > 0


def test_no_empty_text(chunks):
    assert all(c["text"].strip() for c in chunks)


def test_token_limit(chunks):
    over = [c["chunk_id"] for c in chunks if c["n_tokens"] > config.CHUNK_MAX_TOKENS]
    assert not over, over[:5]


def test_section_path_present(chunks):
    no_sec = [c for c in chunks if not c["section_path"] or c["section_path"] == ["(bez sekcji)"]]
    bad = [c["chunk_id"] for c in no_sec if c["doc_id"] != "zboza_giorin"]
    print(f"GIORiN chunks without section: {sum(c['doc_id'] == 'zboza_giorin' for c in no_sec)}")
    assert not bad, bad[:5]
    assert all(c["section_path"] for c in chunks)


def test_chunk_ids_unique(chunks):
    ids = [c["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))


def test_chunk_ids_deterministic(chunks):
    doc_id = "pszenica_producenci"
    doc = load_docs()[doc_id]
    pages, sec = load_pages(doc_id), load_sections()[doc_id]
    a = [c["chunk_id"] for c in chunk_doc(doc, pages, sec)]
    b = [c["chunk_id"] for c in chunk_doc(doc, pages, sec)]
    stored = [c["chunk_id"] for c in chunks if c["doc_id"] == doc_id]
    assert a == b == stored


def test_parse_temp():
    assert parse_temp("4-18")["temp_min_c"] == 4 and parse_temp("4–18")["temp_max_c"] == 18
    t = parse_temp("ok 20")
    assert (t["temp_min_c"], t["temp_max_c"], t["temp_approx"]) == (20, 20, True)
    t = parse_temp("25–30°C (optimum 18–22°C)")
    assert (t["temp_min_c"], t["temp_max_c"], t["temp_opt_min_c"], t["temp_opt_max_c"]) == (25, 30, 18, 22)
    assert parse_temp("Lata ciepłe")["temp_min_c"] is None
    assert parse_temp("P. atrosepticum: 15–24°C; P. carotovorum: 25–28°C")["temp_min_c"] is None


# ----------------------------------------------------------------------------- API
def test_risk_conditions_septoria():
    from rag.search import get_risk_conditions
    rows = get_risk_conditions("pszenica", "septorioza paskowana")
    assert rows and rows[0]["temperature_raw"] == "4-18"
    # inflection / typo tolerant
    assert get_risk_conditions("pszenica", "septoriozy paskowanej")[0]["row"] == rows[0]["row"]
    assert get_risk_conditions("pszenica", "septorjoza paskowana")[0]["row"] == rows[0]["row"]


def test_search_septoria(qdrant_ok):
    from rag.search import search
    res = search("septorioza paskowana warunki", crop="pszenica", k=5)
    assert any("septorioz" in p.text.lower() for p in res)
    assert all(p.crop in ("pszenica", "zboza") for p in res)


def test_default_search_excludes_pesticide_doses(qdrant_ok):
    from rag.search import _store, search
    ids = []
    for q, crop in [("ile litrów herbicydu na hektar", "kukurydza"),
                    ("dawka fungicydu na septoriozę", "pszenica"),
                    ("dobór środka ochrony roślin i dawki", None)]:
        ids += [p.chunk_id for p in search(q, crop=crop, k=10)]
    payloads = _store().get_by_chunk_id(ids)
    assert not [c for c, p in payloads.items() if p["has_pesticide_doses"]]


def test_include_pesticide_doses_flag(qdrant_ok):
    from rag.search import _store, search
    res = search("dobór środka ochrony roślin i dawki herbicydu", crop="kukurydza", k=10,
                 include_pesticide_doses=True)
    payloads = _store().get_by_chunk_id([p.chunk_id for p in res])
    assert any(p["has_pesticide_doses"] for p in payloads.values())


def test_get_passage_and_page(qdrant_ok, chunks):
    from rag.search import get_page, get_passage
    c = next(c for c in chunks if c["doc_id"] == "pszenica_doradcy" and c["prev_id"] and c["next_id"])
    ps = get_passage(c["chunk_id"], with_neighbors=1)
    assert [p.chunk_id for p in ps] == [c["prev_id"], c["chunk_id"], c["next_id"]]
    assert "Ogólne zasady" in get_page("pszenica_doradcy", 17) or get_page("pszenica_doradcy", 17)
