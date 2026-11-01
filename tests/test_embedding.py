import numpy as np
import pytest

from ragforge.core.dense import RRF_K, reciprocal_rank_fusion
from ragforge.core.embedding import ONNXEmbedder


def test_real_onnx_pooling_normalization_and_token_limit(tiny_model) -> None:
    embedder = ONNXEmbedder(tiny_model)
    vectors = embedder.encode(["rollback transaction", "token authentication"])
    assert vectors.shape == (2, 4)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1)
    assert embedder.session.get_providers() == ["CPUExecutionProvider"]
    with pytest.raises(ValueError, match="no silent truncation"):
        embedder.encode(["rollback " * 600])
    with pytest.raises(ValueError, match="nonblank"):
        embedder.encode(["   "])


def test_rrf_uses_ranks_not_incomparable_scores() -> None:
    fused = reciprocal_rank_fusion([("a", 1000), ("b", 1)], [("b", -0.1), ("c", -0.5)], 3)
    assert fused[0][0] == "b"
    assert fused[0][1] == 1 / (RRF_K + 2) + 1 / (RRF_K + 1)
    assert fused == reciprocal_rank_fusion([("a", 0), ("b", -1)], [("b", 10), ("c", 1)], 3)
