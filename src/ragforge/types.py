"""Shared wire types. Paths are portable identifiers, not filesystem authorization."""

import unicodedata
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def validate_relative_path(value: str) -> str:
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError("path must use Unicode NFC")
    parts = value.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10))
    for part in parts:
        if part in {"", ".", ".."} or part.endswith((" ", ".")):
            raise ValueError("path must contain canonical relative segments")
        if part.split(".")[0].upper() in reserved:
            raise ValueError("path contains a Windows reserved name")
    return value


RelativePath = Annotated[
    str,
    Field(min_length=1, max_length=1024, pattern=r'^[^\\:\x00-\x1f<>"|?*]+$'),
    AfterValidator(validate_relative_path),
]


SearchMethod = Literal["bm25", "dense", "hybrid"]
