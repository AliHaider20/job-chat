"""Hybrid BM25 and FAISS retrieval over the uploaded profile."""

import bm25s
import faiss
import numpy as np
import Stemmer

from dataloader import SEPARATOR

WORDS_PER_CHUNK = 100
CHUNK_OVERLAP_WORDS = 15
RRF_K = 60


def chunk_documents(
    profile_text,
    words_per_chunk=WORDS_PER_CHUNK,
    overlap=CHUNK_OVERLAP_WORDS,
):
    """Split each source document into word windows with exact overlap."""
    if words_per_chunk <= 0 or overlap < 0 or overlap >= words_per_chunk:
        raise ValueError("Require words_per_chunk > overlap >= 0")

    chunks = []
    step = words_per_chunk - overlap

    for document in profile_text.split(SEPARATOR):
        document = document.strip()
        if not document:
            continue

        lines = document.splitlines()
        has_source = lines[0].startswith("# Source:")
        source = lines[0].removeprefix("# Source:").strip() if has_source else ""
        body = "\n".join(lines[1:]).strip() if has_source else document
        words = body.split()

        for start in range(0, len(words), step):
            chunk = " ".join(words[start : start + words_per_chunk])
            if chunk:
                chunks.append(_label(source, chunk))
            if start + words_per_chunk >= len(words):
                break

    return chunks


def _label(source, text):
    return f"[{source}]\n{text}" if source else text


def _reciprocal_rank_fusion(*rankings, k=RRF_K):
    scores = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            if chunk_id >= 0:
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=scores.get, reverse=True)


class ProfileIndex:
    def __init__(self, chunks, embed_fn):
        self.chunks = list(chunks)
        self.embed_fn = embed_fn
        self.stemmer = Stemmer.Stemmer("english")

        if self.chunks:
            tokens = bm25s.tokenize(
                self.chunks,
                stopwords="en",
                stemmer=self.stemmer,
                show_progress=False,
            )
            self.bm25 = bm25s.BM25()
            self.bm25.index(tokens, show_progress=False)

            vectors = np.ascontiguousarray(embed_fn(self.chunks), dtype=np.float32)
            faiss.normalize_L2(vectors)
            self.faiss_index = faiss.IndexFlatIP(vectors.shape[1])
            self.faiss_index.add(vectors)
        else:
            self.bm25 = None
            self.faiss_index = None

    def search(self, query, k=5):
        """Return chunks ranked by reciprocal-rank fusion of BM25 and cosine."""
        if not self.chunks or not query.strip() or k <= 0:
            return []

        candidate_count = min(k, len(self.chunks))
        query_tokens = bm25s.tokenize(
            [query],
            stopwords="en",
            stemmer=self.stemmer,
            show_progress=False,
        )
        bm25_ids, _ = self.bm25.retrieve(
            query_tokens,
            k=candidate_count,
            show_progress=False,
        )
        dense_query = np.ascontiguousarray(self.embed_fn([query]), dtype=np.float32)
        faiss.normalize_L2(dense_query)
        _, faiss_ids = self.faiss_index.search(dense_query, candidate_count)

        fused_ids = _reciprocal_rank_fusion(bm25_ids[0], faiss_ids[0])
        return [self.chunks[i] for i in fused_ids[:candidate_count]]

    def search_text(self, query, k=5):
        found = self.search(query, k)
        return "\n\n---\n\n".join(found) if found else "(No relevant excerpts found.)"
