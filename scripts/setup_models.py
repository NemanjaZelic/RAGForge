"""Explicit online setup; verify/reuse models and atomically publish new downloads.

This maintenance script is never imported by local retrieval or build.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from prepare_models import CANDIDATES
from prepare_reranker import MMARCO_MODEL, MMARCO_REVISION
from prepare_reranker import MODEL as ENGLISH_MODEL
from prepare_reranker import REVISION as ENGLISH_REVISION

from ragforge.artifacts.builder import publish_new
from ragforge.core.embedding import ModelSpec, model_spec
from ragforge.core.rerank import ONNXReranker, RerankerSpec, reranker_spec
from ragforge.core.source import is_link
from ragforge.jobs.build import atomic_json
from ragforge.quickstart import ModelPaths, state_directory

ROOT = Path(__file__).resolve().parents[1]


def prepare(
    destination: Path,
    *,
    script: Path,
    script_args: list[str],
    expected_id: str,
    expected_revision: str,
    validate: Callable[[Path], ModelSpec | RerankerSpec],
    offline: bool,
) -> Path:
    def checked(path: Path) -> None:
        spec = validate(path)
        if (spec.model_id, spec.revision) != (expected_id, expected_revision):
            raise ValueError(f"Unexpected model in {destination}; existing files were preserved.")

    destination = destination.absolute()
    if os.path.lexists(destination):
        checked(destination)
        print(f"Reused verified model: {destination}", flush=True)
        return destination
    if offline:
        raise ValueError(f"Model missing: {destination}. Run setup without -Offline to download.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    parent = destination.parent.resolve(strict=True)
    destination = parent / destination.name
    stage = Path(tempfile.mkdtemp(prefix=".ragforge-setup-", dir=parent))
    # Reserve our unique sibling name, then let the existing provisioner create it.
    if stage.resolve().parent != parent or is_link(stage.lstat()):
        raise ValueError("invalid model staging directory")
    stage.rmdir()
    try:
        subprocess.run([sys.executable, str(script), *script_args, str(stage)], check=True)
        checked(stage)
        publish_new(stage, destination)
    finally:
        if stage.exists():
            if (
                stage.resolve().parent != parent
                or is_link(stage.lstat())
                or not stage.name.startswith(".ragforge-setup-")
            ):
                raise ValueError("refusing cleanup outside owned model staging directory")
            shutil.rmtree(stage)
    print(f"Prepared model: {destination}", flush=True)
    return destination


def setup_models(
    project: Path,
    models: Path,
    *,
    offline: bool = False,
    document_language: Literal["multilingual", "en"] = "multilingual",
    accelerator: Literal["cpu", "intel-gpu"] = "cpu",
) -> ModelPaths:
    if document_language not in {"multilingual", "en"}:
        raise ValueError("document language must be multilingual or en")
    if accelerator not in {"cpu", "intel-gpu"}:
        raise ValueError("accelerator must be cpu or intel-gpu")
    gpu = accelerator == "intel-gpu"
    if gpu:
        if document_language != "en":
            raise ValueError("Intel GPU profile requires --document-language en")
        from ragforge.core.intel_gpu import check_gpu_available

        check_gpu_available()
    folder = (
        "ms-marco-minilm-gpu-reranker"
        if gpu
        else ("ms-marco-minilm-reranker" if document_language == "en" else "mmarco-minilm-reranker")
    )
    choice = (
        "minilm-l6-gpu" if gpu else ("minilm-l6" if document_language == "en" else "mmarco-minilm")
    )
    candidate = CANDIDATES["e5-small"]
    query = prepare(
        models / "e5-small",
        script=ROOT / "scripts/prepare_models.py",
        script_args=["e5-small"],
        expected_id=str(candidate["id"]),
        expected_revision=str(candidate["revision"]),
        validate=model_spec,
        offline=offline,
    )
    reranker = prepare(
        models / folder,
        script=ROOT / "scripts/prepare_reranker.py",
        script_args=["--model", choice],
        expected_id=ENGLISH_MODEL if document_language == "en" else MMARCO_MODEL,
        expected_revision=ENGLISH_REVISION if document_language == "en" else MMARCO_REVISION,
        validate=reranker_spec,
        offline=offline,
    )
    expected_runtime = "openvino-gpu-f16" if gpu else "onnxruntime-cpu"
    if reranker_spec(reranker).runtime != expected_runtime:
        raise ValueError("Prepared reranker runtime does not match the selected accelerator")
    if gpu:
        # Compile and execute neutral data before replacing the active setup.
        ONNXReranker(reranker, threads=4, workers=2, cache_batches=0).score(
            "warmup", ["warmup document source"]
        )
    paths = ModelPaths(
        query_model=str(query),
        reranker=str(reranker),
        document_language=document_language,
        accelerator=accelerator,
    )
    atomic_json(state_directory(project) / "models.json", paths.model_dump(mode="json"))
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-directory", type=Path, default=ROOT / "models")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--document-language", choices=["multilingual", "en"], default="multilingual"
    )
    parser.add_argument("--accelerator", choices=["cpu", "intel-gpu"], default="cpu")
    args = parser.parse_args()
    try:
        setup_models(
            ROOT,
            args.models_directory,
            offline=args.offline,
            document_language=args.document_language,
            accelerator=args.accelerator,
        )
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
