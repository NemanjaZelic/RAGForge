"""Source-proven acronym hints for lexical matching and reranking, never answers."""

import re
from collections import OrderedDict
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ragforge.artifacts.manifest import BundleManifest
from ragforge.core.source import is_link
from ragforge.core.sqlite import SQLiteEngine
from ragforge.types import ContractModel, RelativePath, Sha256


def canonical(text: str) -> str:
    return " ".join(text.split()).casefold()


class AliasProof(ContractModel):
    source_path: RelativePath
    source_sha256: Sha256
    quote: Annotated[str, Field(min_length=5, max_length=256)]


class Acronym(ContractModel):
    short: Annotated[str, Field(pattern=r"^[A-Za-z]{2,10}$")]
    long_form: Annotated[str, Field(min_length=3, max_length=120)]
    proofs: Annotated[list[AliasProof], Field(min_length=3, max_length=8)]

    @model_validator(mode="after")
    def explicit_definition(self) -> Self:
        initials = "".join(w[0] for w in re.findall(r"[A-Za-z]+", self.long_form))
        if initials.casefold() != self.short.casefold():
            raise ValueError("acronym initials do not match expansion")
        expected = canonical(self.long_form + " (" + self.short + ")")
        if any(canonical(p.quote) != expected for p in self.proofs):
            raise ValueError("acronym proofs must explicitly define the expansion")
        if len({p.source_path for p in self.proofs}) != len(self.proofs):
            raise ValueError("acronym requires distinct source proofs")
        return self


class AliasBank(ContractModel):
    version: Literal["source-acronyms-v1"] = "source-acronyms-v1"
    catalogue_sha256: Sha256
    definitions: Annotated[list[Acronym], Field(min_length=1, max_length=2048)]

    @model_validator(mode="after")
    def unique_names(self) -> Self:
        if len({d.short.casefold() for d in self.definitions}) != len(self.definitions):
            raise ValueError("duplicate acronym definition")
        return self

    def mapping(self) -> dict[str, str]:
        return {d.short.casefold(): d.long_form for d in self.definitions}


def read_aliases(path: Path) -> AliasBank:
    if is_link(path.lstat()) or not path.is_file() or path.stat().st_size > 4 * 1024**2:
        raise ValueError("unsafe or oversized acronym bank")
    return AliasBank.model_validate_json(path.read_text(encoding="utf-8"))


def verify_aliases(path: Path, manifest: BundleManifest, engine: SQLiteEngine) -> AliasBank:
    bank = read_aliases(path)
    documents = {d.source_path: d for d in manifest.collections[0].documents}
    cache: OrderedDict[str, str] = OrderedDict()
    with engine._connect() as connection:
        for definition in bank.definitions:
            for proof in definition.proofs:
                doc = documents.get(proof.source_path)
                if doc is None or doc.content_sha256 != proof.source_sha256:
                    raise ValueError("acronym source differs from verified inventory")
                if doc.document_id not in cache:
                    cache[doc.document_id] = canonical(
                        "\n".join(
                            row[0]
                            for row in connection.execute(
                                "SELECT text FROM chunks WHERE document_id=? "
                                "ORDER BY ordinal LIMIT 16",
                                (doc.document_id,),
                            )
                        )[:8192]
                    )
                    if len(cache) > 128:
                        cache.popitem(last=False)
                cache.move_to_end(doc.document_id)
                if canonical(proof.quote) not in cache[doc.document_id]:
                    raise ValueError("acronym definition is absent from indexed source lead")
    return bank


def expand_query(query: str, aliases: dict[str, str]) -> str:
    """Append at most three uppercase names; preserve every original query term."""
    terms = list(dict.fromkeys(re.findall(r"[^\W_]+", query)))
    if len(terms) > 64:
        return query
    selected = []
    expanded = query
    for term in terms:
        # Case-insensitive matching mistakes ordinary 'in'/'as' for IN/AS.
        if not term.isupper():
            continue
        name = aliases.get(term.casefold())
        if name is None or name in selected or canonical(name) in canonical(query):
            continue
        proposed = expanded + " " + name
        if len(proposed) > 8192 or len(set(re.findall(r"[^\W_]+", proposed))) > 64:
            continue
        selected.append(name)
        expanded = proposed
        if len(selected) == 3:
            break
    return expanded
