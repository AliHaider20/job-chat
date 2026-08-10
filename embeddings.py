"""Sentence embeddings via fastembed (ONNX runtime, no torch dependency).

Vectors come back L2-normalised, so a dot product is cosine similarity.
"""

from functools import lru_cache

import numpy as np

from config import get_settings


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(get_settings().embedding_model)


def embed(texts) -> np.ndarray:
    """Embed a sequence of strings into a (n, dim) float32 matrix."""
    texts = list(texts)
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    return np.asarray(list(_model().embed(texts)), dtype=np.float32)
