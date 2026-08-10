"""Retrieval over the profile documents.

The corpus is three documents and a few dozen chunks, so similarity is computed
directly against an in-memory matrix. A vector database would add a dependency
and an external service without changing the result at this size.

Retrieval is used only for narrowly scoped questions. The preset actions always
receive the full profile, because a retrieval miss there would silently corrupt
an ATS score or a fit review.
"""

import numpy as np

from dataloader import SEPARATOR

TARGET_CHUNK_CHARS = 600


def chunk_documents(profile_text, target_chars=TARGET_CHUNK_CHARS):
    """Split the profile into retrievable chunks, each labelled with its source."""
    chunks = []

    for document in profile_text.split(SEPARATOR):
        document = document.strip()
        if not document:
            continue

        lines = document.splitlines()
        source = lines[0].removeprefix("# Source:").strip() if lines[0].startswith("# Source:") else ""
        body = "\n".join(lines[1:]).strip() if source else document

        current = []
        length = 0
        for paragraph in (p.strip() for p in body.split("\n\n")):
            if not paragraph:
                continue
            if current and length + len(paragraph) > target_chars:
                chunks.append(_label(source, current))
                current, length = [], 0
            current.append(paragraph)
            length += len(paragraph)

        if current:
            chunks.append(_label(source, current))

    return chunks


def _label(source, paragraphs):
    body = "\n\n".join(paragraphs)
    return f"[{source}]\n{body}" if source else body


class ProfileIndex:
    def __init__(self, chunks, embed_fn):
        self.chunks = list(chunks)
        if self.chunks:
            vectors = embed_fn(self.chunks)
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            self.vectors = vectors / np.where(norms == 0, 1, norms)
        else:
            self.vectors = np.zeros((0, 0), dtype=np.float32)
        self.embed_fn = embed_fn

    def search(self, query, k=5):
        """Return the k chunks most similar to the query, best first."""
        if not self.chunks or not query.strip():
            return []

        vector = self.embed_fn([query])[0]
        norm = np.linalg.norm(vector)
        if norm:
            vector = vector / norm

        similarities = self.vectors @ vector
        top = np.argsort(similarities)[::-1][:k]
        return [self.chunks[i] for i in top]

    def search_text(self, query, k=5):
        found = self.search(query, k)
        return "\n\n---\n\n".join(found) if found else "(No relevant excerpts found.)"
