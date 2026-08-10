"""Chunking and retrieval, with a bag-of-words embedder so tests stay offline."""

import numpy as np
import pytest

from dataloader import SEPARATOR
from retrieval import ProfileIndex, chunk_documents

VOCAB = ["faiss", "kubernetes", "volunteer", "python", "rust"]


def fake_embed(texts):
    vectors = []
    for text in texts:
        lowered = text.lower()
        vectors.append([float(word in lowered) for word in VOCAB])
    return np.array(vectors, dtype=np.float32)


def profile(*documents):
    return SEPARATOR.join(documents)


def test_chunks_carry_their_source_label():
    text = profile("# Source: resume\n\nWorked with FAISS.", "# Source: volunteer\n\nTaught Python.")
    chunks = chunk_documents(text)
    assert any(c.startswith("[resume]") for c in chunks)
    assert any(c.startswith("[volunteer]") for c in chunks)


def test_content_survives_chunking():
    chunks = chunk_documents(profile("# Source: resume\n\nWorked with FAISS."))
    assert "Worked with FAISS." in "\n".join(chunks)


def test_long_documents_split_into_several_chunks():
    body = "\n\n".join(f"Paragraph {i} " + "x" * 200 for i in range(10))
    chunks = chunk_documents(profile(f"# Source: resume\n\n{body}"), target_chars=300)
    assert len(chunks) > 1


def test_short_documents_stay_whole():
    assert len(chunk_documents(profile("# Source: resume\n\nShort."))) == 1


def test_empty_input_yields_no_chunks():
    assert chunk_documents("") == []


def test_documents_without_a_source_header_still_chunk():
    chunks = chunk_documents("Just a body with no header.")
    assert len(chunks) == 1
    assert "Just a body" in chunks[0]


class TestSearch:
    @pytest.fixture
    def index(self):
        return ProfileIndex(
            ["[resume] Built a FAISS index", "[volunteer] Volunteer teaching", "[projects] Python tooling"],
            fake_embed,
        )

    def test_search_ranks_the_matching_chunk_first(self, index):
        assert "FAISS" in index.search("faiss", k=1)[0]
        assert "Volunteer" in index.search("volunteer", k=1)[0]

    def test_search_respects_k(self, index):
        assert len(index.search("python", k=2)) == 2

    def test_k_larger_than_the_corpus_is_safe(self, index):
        assert len(index.search("python", k=99)) == 3

    def test_empty_query_returns_nothing(self, index):
        assert index.search("   ") == []

    def test_search_text_joins_results(self, index):
        assert "---" in index.search_text("python", k=2)

    def test_search_text_reports_when_nothing_is_found(self, index):
        assert "No relevant excerpts" in index.search_text("", k=3)


def test_an_empty_index_does_not_crash():
    empty = ProfileIndex([], fake_embed)
    assert empty.search("anything") == []
    assert "No relevant excerpts" in empty.search_text("anything")
