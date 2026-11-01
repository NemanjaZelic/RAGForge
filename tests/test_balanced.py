import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ragforge.artifacts.manifest import BundleManifest
from ragforge.core.contracts import RetrieveRequest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "manifests"


def balanced_data() -> dict[str, Any]:
    return json.loads((EXAMPLES / "balanced.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("profile", ["minimal", "balanced"])
def test_documented_manifest_roundtrip(profile: str) -> None:
    model = BundleManifest.model_validate_json((EXAMPLES / f"{profile}.json").read_text())
    assert BundleManifest.model_validate_json(model.model_dump_json()) == model


@pytest.mark.parametrize("method", ["bm25", "dense", "hybrid", None])
def test_query_method_is_separate_from_build_profile(method: str | None) -> None:
    request = RetrieveRequest.model_validate({"query": "rollback", "search_method": method})
    assert request.search_method == method
    assert "profile" not in request.model_dump()


@pytest.mark.parametrize(
    "changes",
    [
        {"capabilities": ["bm25"]},
        {"capabilities": ["bm25", "hybrid", "hybrid"]},
        {"default_search_method": "bm25"},
        {"query_model": None},
        {"profile": "minimal"},
    ],
)
def test_balanced_rejects_inconsistent_profile(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        BundleManifest.model_validate({**balanced_data(), **changes})


@pytest.mark.parametrize("fault", ["dimensions", "dense", "model", "external", "duplicate"])
def test_balanced_requires_consistent_inventoried_local_artifacts(fault: str) -> None:
    data = copy.deepcopy(balanced_data())
    if fault == "dimensions":
        data["query_model"]["dimensions"] = 2
    elif fault == "dense":
        data["collections"][0]["dense_index"]["path"] = "missing.index"
    elif fault == "model":
        data["files"] = data["files"][:-1]
    elif fault == "external":
        data["query_model"]["files"] = ["https://example.com/model"]
    else:
        data["query_model"]["files"] *= 2
    with pytest.raises(ValidationError):
        BundleManifest.model_validate(data)


def test_reject_unknown_method() -> None:
    with pytest.raises(ValidationError):
        RetrieveRequest(query="x", search_method="remote")
