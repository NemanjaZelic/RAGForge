"""Bounded character chunks with deterministic IDs and source locations."""

import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import replace
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ragforge.core.contracts import SourceLocation
from ragforge.core.parse import ParsedDocument, TextBlock
from ragforge.types import ContractModel, Identifier, Sha256

CHUNKER_VERSION = "chars-v1"


class ChunkConfig(ContractModel):
    strategy: Literal["blocks", "sections"] = "blocks"
    chunk_size_chars: Annotated[int, Field(ge=1, le=100000)] = 1000
    overlap_chars: Annotated[int, Field(ge=0)] = 100

    @model_validator(mode="after")
    def valid_overlap(self) -> Self:
        if self.overlap_chars >= self.chunk_size_chars:
            raise ValueError("overlap must be smaller than chunk size")
        return self


class Chunk(ContractModel):
    collection_id: Identifier
    document_id: Sha256
    chunk_id: Sha256
    ordinal: Annotated[int, Field(ge=0)]
    text: Annotated[str, Field(min_length=1, max_length=100000)]
    source: SourceLocation
    kind: Literal["text", "code"]
    block_index: Annotated[int, Field(ge=0)]
    char_start: Annotated[int, Field(ge=0)]
    char_end: Annotated[int, Field(ge=1)]


def chunker_version(config: ChunkConfig) -> str:
    return CHUNKER_VERSION if config.strategy == "blocks" else "section-chars-v2"


def pipeline_hash(document: ParsedDocument, config: ChunkConfig) -> str:
    options = config.model_dump(exclude={"strategy"})
    payload = {
        "parser_version": document.parser_version,
        "chunker_version": chunker_version(config),
        **options,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _location(path: str, block: TextBlock, text: str, line_offset: int) -> SourceLocation:
    line_start = line_end = None
    if block.line_start is not None:
        line_start = block.line_start + line_offset
        line_end = line_start + text[:-1].count("\n")
    return SourceLocation(
        path=path, page=block.page, line_start=line_start, line_end=line_end, section=block.section
    )


def _blocks(document: ParsedDocument, config: ChunkConfig) -> Iterator[tuple[int, TextBlock]]:
    """Coalesce neighboring prose within a section, physical page and line range.

    HTML paragraph boundaries no longer force tiny retrieval units. Code remains
    separate. The bounded buffer never crosses pages or invents source line numbers.
    block_index identifies the first original block; offsets are in the coalesced block.
    """
    pending: TextBlock | None = None
    first = 0
    for index, block in enumerate(document.blocks):
        contiguous_lines = pending is not None and (
            (pending.line_start is None and block.line_start is None)
            or (pending.line_end is not None and block.line_start == pending.line_end + 1)
        )
        if (
            config.strategy == "sections"
            and pending is not None
            and pending.kind == block.kind == "text"
            and pending.section == block.section
            and pending.page == block.page
            and contiguous_lines
            and len(pending.text) + len(block.text) + 1 <= 100000
        ):
            separator = "" if pending.line_start is not None else "\n"
            pending = replace(
                pending, text=pending.text + separator + block.text, line_end=block.line_end
            )
        else:
            if pending is not None:
                yield first, pending
            first, pending = index, block
    if pending is not None:
        yield first, pending


def iter_chunks(
    document: ParsedDocument,
    config: ChunkConfig | None = None,
    *,
    max_chunks: int = 10000,
    max_output_chars: int = 10000000,
) -> Iterator[Chunk]:
    config = config or ChunkConfig()
    if type(max_chunks) is not int or max_chunks < 1:
        raise ValueError("max_chunks must be a positive integer")
    if type(max_output_chars) is not int or max_output_chars < 1:
        raise ValueError("max_output_chars must be a positive integer")
    output_chars = 0
    config_hash = pipeline_hash(document, config)
    ordinal = 0
    for block_index, block in _blocks(document, config):
        start = 0
        line_offset = 0
        while start < len(block.text):
            end = min(start + config.chunk_size_chars, len(block.text))
            if end < len(block.text):
                # Prefer a line boundary in the latter half, then a word boundary.
                lower = start + max(1, (end - start) // 2)
                newline = block.text.rfind("\n", lower, end)
                if newline >= lower:
                    end = newline + 1
                elif block.kind != "code":
                    candidates = list(re.finditer(r"\s+", block.text[lower:end]))
                    if candidates:
                        end = lower + candidates[-1].end()
            text = block.text[start:end]
            if text.strip():
                if ordinal >= max_chunks:
                    raise ValueError("max_chunks exceeded")
                output_chars += len(text)
                if output_chars > max_output_chars:
                    raise ValueError("max_output_chars exceeded")
                payload = [
                    "ragforge-chunk-v1",
                    document.record.document_id,
                    document.record.content_sha256,
                    config_hash,
                    ordinal,
                ]
                chunk_id = hashlib.sha256(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                yield Chunk(
                    collection_id=document.collection_id,
                    document_id=document.record.document_id,
                    chunk_id=chunk_id,
                    ordinal=ordinal,
                    text=text,
                    source=_location(document.record.source_path, block, text, line_offset),
                    kind=block.kind,
                    block_index=block_index,
                    char_start=start,
                    char_end=end,
                )
                ordinal += 1
            if end == len(block.text):
                break
            next_start = max(start + 1, end - config.overlap_chars)
            line_offset += block.text.count("\n", start, next_start)
            start = next_start


def chunk_document(
    document: ParsedDocument,
    config: ChunkConfig | None = None,
    *,
    max_chunks: int = 10000,
    max_output_chars: int = 10000000,
) -> list[Chunk]:
    """Compatibility list API; index builds consume iter_chunks without materialization."""
    return list(
        iter_chunks(document, config, max_chunks=max_chunks, max_output_chars=max_output_chars)
    )
