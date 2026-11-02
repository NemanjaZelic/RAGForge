"""Operator-controlled version pointers. Updates take effect after an explicit restart."""

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, ValidationError, model_validator

from ragforge.artifacts.builder import publish_new
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.engine import BundleEngine
from ragforge.core.source import is_link
from ragforge.jobs.build import atomic_json
from ragforge.jobs.ingest import job_lock
from ragforge.shared.policy import JWTVerifier, ScopedEngine, SharedPolicy
from ragforge.types import ContractModel, Identifier, SearchMethod, Sha256


class BundleReference(ContractModel):
    path: Annotated[str, Field(min_length=1, max_length=4096)]
    build_id: Sha256
    smoke_methods: Annotated[list[SearchMethod], Field(min_length=1, max_length=3)]

    @model_validator(mode="after")
    def absolute_unique(self) -> Self:
        if not Path(self.path).is_absolute():
            raise ValueError("deployment bundle reference must be absolute on this host")
        if len(set(self.smoke_methods)) != len(self.smoke_methods):
            raise ValueError("duplicate smoke method")
        return self


class DeploymentState(ContractModel):
    schema_version: Literal["1"] = "1"
    mode: Literal["shared"] = "shared"
    collection_id: Identifier
    auth_policy: Annotated[str, Field(min_length=1, max_length=4096)]
    active: BundleReference
    previous: Annotated[list[BundleReference], Field(max_length=10)] = []

    @model_validator(mode="after")
    def valid_history(self) -> Self:
        ids = [self.active.build_id, *(r.build_id for r in self.previous)]
        if len(ids) != len(set(ids)) or not Path(self.auth_policy).is_absolute():
            raise ValueError("invalid deployment history or policy reference")
        return self


def read_deployment(root: Path) -> DeploymentState:
    if is_link(root.lstat()) or not root.is_dir():
        raise ValueError("deployment must be a real directory")
    control = root / "deployment.json"
    if is_link(control.lstat()) or control.stat().st_size > 128 * 1024:
        raise ValueError("unsafe/oversized deployment state")
    try:
        return DeploymentState.model_validate_json(control.read_bytes())
    except ValidationError:
        raise ValueError("invalid deployment state; check its schema") from None


def candidate(
    artifact: Path,
    policy: SharedPolicy,
    smoke_query: str,
    *,
    expected_collection: str | None = None,
    expected_build_id: str | None = None,
    expected_document_id: str | None = None,
) -> tuple[BundleReference, str]:
    engine = BundleEngine(artifact)
    if expected_collection is not None and engine.collection.collection_id != expected_collection:
        raise ValueError("new bundle must preserve the deployment collection ID")
    if expected_build_id is not None and engine.manifest.build_id != expected_build_id:
        raise ValueError("stored bundle version does not match its verified build ID")
    JWTVerifier(policy)
    ScopedEngine(engine, policy)  # Validate every configured collection/source grant.
    for method in engine.manifest.capabilities:
        response = engine.retrieve(
            RetrieveRequest(query=smoke_query, search_method=method, top_k=3, max_output_chars=4000)
        )
        if not response.results or (
            expected_document_id is not None
            and not any(row.document_id == expected_document_id for row in response.results)
        ):
            raise ValueError("candidate failed a required retrieval smoke test")
    return BundleReference(
        path=str(artifact.resolve(strict=True)),
        build_id=engine.manifest.build_id,
        smoke_methods=engine.manifest.capabilities,
    ), engine.collection.collection_id


def create_deployment(
    artifact: Path,
    output: Path,
    auth_file: Path,
    smoke_query: str,
    *,
    expected_document_id: str | None = None,
) -> DeploymentState:
    from ragforge.shared.client import ConnectionProfile

    policy = SharedPolicy.read(auth_file)
    reference, collection = candidate(
        artifact, policy, smoke_query, expected_document_id=expected_document_id
    )
    output = output.absolute()
    if output.resolve().is_relative_to(artifact.resolve()):
        raise ValueError("deployment state must be outside the immutable bundle")
    if os.path.lexists(output):
        raise FileExistsError("deployment output exists; choose a new directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    parent = output.parent.resolve(strict=True)
    output = parent / output.name
    state = DeploymentState(
        collection_id=collection, auth_policy=str(auth_file.resolve(strict=True)), active=reference
    )
    stage = Path(tempfile.mkdtemp(prefix=".ragforge-deployment-", dir=parent))
    try:
        atomic_json(stage / "deployment.json", state.model_dump(mode="json"))
        authority = urlsplit(str(policy.resource_url))
        profile = ConnectionProfile(
            endpoint=policy.resource_url.__class__(authority.scheme + "://" + authority.netloc)
        )
        atomic_json(stage / "connection.json", profile.model_dump(mode="json"))
        command = [
            str(Path(sys.executable).absolute()),
            "-m",
            "ragforge",
            "serve",
            "--deployment",
            str(output),
            "--transport",
            "http",
            "--auth-file",
            state.auth_policy,
        ]
        atomic_json(
            stage / "serve.json",
            {
                "command": command,
                "started": False,
                "note": "Review bind/TLS flags; the resource URL describes the external endpoint.",
            },
        )
        publish_new(stage, output)
    finally:
        if stage.exists():
            if (
                stage.resolve().parent != parent
                or is_link(stage.lstat())
                or not stage.name.startswith(".ragforge-deployment-")
            ):
                raise ValueError("unsafe private deployment stage cleanup")
            shutil.rmtree(stage)
    return state


def activate(
    root: Path, artifact: Path, smoke_query: str, *, expected_document_id: str | None = None
) -> DeploymentState:
    read_deployment(root)
    with job_lock(root):
        previous = read_deployment(root)
        reference, _ = candidate(
            artifact,
            SharedPolicy.read(Path(previous.auth_policy)),
            smoke_query,
            expected_collection=previous.collection_id,
            expected_document_id=expected_document_id,
        )
        if reference == previous.active:
            return previous
        history = (
            [previous.active] if previous.active.build_id != reference.build_id else []
        ) + previous.previous
        history = [item for item in history if item.build_id != reference.build_id][:10]
        state = previous.model_copy(update={"active": reference, "previous": history})
        atomic_json(root / "deployment.json", state.model_dump(mode="json"))
        return state


def rollback(
    root: Path, smoke_query: str, *, expected_document_id: str | None = None
) -> DeploymentState:
    read_deployment(root)
    with job_lock(root):
        previous = read_deployment(root)
        if not previous.previous:
            raise ValueError("deployment has no previous verified version")
        target = previous.previous[0]
        reference, _ = candidate(
            Path(target.path),
            SharedPolicy.read(Path(previous.auth_policy)),
            smoke_query,
            expected_collection=previous.collection_id,
            expected_build_id=target.build_id,
            expected_document_id=expected_document_id,
        )
        state = previous.model_copy(
            update={"active": reference, "previous": [previous.active, *previous.previous[1:]][:10]}
        )
        atomic_json(root / "deployment.json", state.model_dump(mode="json"))
        return state


def state_summary(state: DeploymentState) -> dict[str, object]:
    return {
        "active_build_id": state.active.build_id,
        "previous_build_ids": [r.build_id for r in state.previous],
        "smoke_methods": state.active.smoke_methods,
        "restart_required": True,
        "server_started": False,
        "remote_resources_created": False,
    }
