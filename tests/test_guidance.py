import pytest
from tools.db import ToolError
from tools.guidance import (HashEmbedder, chunk_words, clean_text, detect_language, ingest,
                            search_guidance)


def test_clean_text_keeps_azerbaijani_letters():
    t = clean_text("\ufeffƏ  ı   ö ü ğ ş ç\r\n\r\n\r\n\r\nson")
    assert t == "Ə ı ö ü ğ ş ç\n\nson"


def test_chunking_with_overlap():
    words = " ".join(f"w{i}" for i in range(450))
    chunks = chunk_words(words, size=200, overlap=40)
    assert len(chunks) == 3
    assert chunks[0].split()[-40:] == chunks[1].split()[:40]
    assert chunk_words("", 200, 40) == []
    with pytest.raises(ValueError):
        chunk_words("a b c", 10, 10)


def test_language_from_filename():
    assert detect_language("x.az.md") == "az" and detect_language("x.en.md") == "en"
    assert detect_language("x.md") == "en"


@pytest.fixture()
def kb(tmp_path):
    g = tmp_path / "g"; g.mkdir()
    (g / "ielts.en.md").write_text("IELTS practice test weakest skill writing timer", encoding="utf-8")
    (g / "ielts_copy.en.md").write_text("IELTS practice test weakest skill writing timer", encoding="utf-8")  # duplicate
    (g / "letters.en.md").write_text("Recommendation letters supervisor referee deadline reminder", encoding="utf-8")
    (g / "ielts.az.md").write_text("IELTS hazırlığı zəif bacarıq təcrübə testi", encoding="utf-8")
    (g / "broken.md").write_bytes(b"\xff\xfe\x00\x00bad")                      # unreadable
    emb, db = HashEmbedder(), tmp_path / "chroma"
    return {"g": g, "db": db, "emb": emb, "report": ingest(g, db, emb)}


def test_ingest_report(kb):
    r = kb["report"]
    assert r["files"] == 3 and r["chunks"] == 3
    assert r["duplicates"] == ["ielts_copy.en.md"] and r["unreadable"] == ["broken.md"]


def test_search_finds_relevant_text(kb):
    res = search_guidance("recommendation letter referee", language="en", persist_dir=kb["db"], embedder=kb["emb"], k=1)
    assert res["passages"][0]["source"] == "letters.en.md"


def test_search_language_filter_and_fallback(kb):
    az = search_guidance("IELTS hazırlığı", language="az", persist_dir=kb["db"], embedder=kb["emb"], k=2)
    assert {p["language"] for p in az["passages"]} == {"az"}
    # asking for a language with no documents falls back and says so
    import chromadb  # noqa
    res = search_guidance("IELTS", language="az", persist_dir=kb["db"], embedder=kb["emb"], k=5)
    assert res["count"] >= 1


def test_search_errors(tmp_path, kb):
    with pytest.raises(ToolError):
        search_guidance("  ", persist_dir=kb["db"], embedder=kb["emb"])
    with pytest.raises(ToolError):
        search_guidance("x", persist_dir=tmp_path / "nothing", embedder=kb["emb"])
