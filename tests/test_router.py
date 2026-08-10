"""Router logic, tested with a controlled embedder rather than the real model.

Model quality is a separate concern; what matters here is that ambiguity falls
back to the full profile instead of silently answering without evidence.
"""

import numpy as np
import pytest

from router import FULL, SPECIFIC, TRIVIAL, SemanticRouter

REFERENCES = {TRIVIAL: ["GREET"], SPECIFIC: ["NARROW"], FULL: ["BROAD"]}
AXIS = {"GREET": 0, "NARROW": 1, "BROAD": 2}


def fake_embed(texts):
    """One-hot per route keyword; anything else is equidistant from all three."""
    vectors = []
    for text in texts:
        vector = np.zeros(3, dtype=np.float32)
        for token, axis in AXIS.items():
            if token in text:
                vector[axis] = 1.0
        if not vector.any():
            vector[:] = 1 / np.sqrt(3)
        vectors.append(vector)
    return np.array(vectors, dtype=np.float32)


@pytest.fixture
def router():
    return SemanticRouter(fake_embed, references=REFERENCES)


@pytest.mark.parametrize(
    "query,expected",
    [("GREET", TRIVIAL), ("NARROW", SPECIFIC), ("BROAD", FULL)],
)
def test_confident_queries_reach_their_route(router, query, expected):
    assert router.route(query) == expected


def test_ambiguous_queries_fall_back_to_full(router):
    """Equidistant from every route: answering without the profile is the costly error."""
    assert router.route("nothing in particular") == FULL


def test_a_tie_between_trivial_and_specific_falls_back_to_full(router):
    assert router.route("GREET NARROW") == FULL


@pytest.mark.parametrize("query", ["", "   ", None])
def test_empty_queries_fall_back_to_full(router, query):
    assert router.route(query) == FULL


def test_a_high_threshold_forces_the_safe_route():
    """An exact match scores 1.0 here, so the bar has to sit above it."""
    strict = SemanticRouter(fake_embed, references=REFERENCES, min_score=1.1)
    assert strict.route("GREET") == FULL


def test_a_wide_margin_requirement_forces_the_safe_route():
    strict = SemanticRouter(fake_embed, references=REFERENCES, min_margin=1.1)
    assert strict.route("NARROW") == FULL


def test_shipped_thresholds_leave_room_for_a_confident_match():
    from router import MIN_MARGIN, MIN_SCORE

    assert 0 < MIN_SCORE < 1
    assert 0 < MIN_MARGIN < 1


def test_scores_cover_every_route(router):
    assert set(router.scores("GREET")) == {TRIVIAL, SPECIFIC, FULL}


def test_centroids_are_normalised(router):
    assert np.allclose(np.linalg.norm(router.centroids, axis=1), 1.0)


class TestRealReferenceSet:
    """The shipped reference queries must be well formed."""

    def test_every_route_has_examples(self):
        from router import REFERENCE_QUERIES

        assert set(REFERENCE_QUERIES) == {TRIVIAL, SPECIFIC, FULL}
        for examples in REFERENCE_QUERIES.values():
            assert len(examples) >= 5

    def test_examples_are_unique_across_routes(self):
        from router import REFERENCE_QUERIES

        seen = [q for examples in REFERENCE_QUERIES.values() for q in examples]
        assert len(seen) == len(set(seen))
