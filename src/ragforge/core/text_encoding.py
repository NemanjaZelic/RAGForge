"""Deterministic local text decoding; never replace bytes or rewrite a source."""

import codecs
import re


def decode_text(raw: bytes, *, html: bool = False) -> tuple[str, str, bool]:
    """Return text, recorded codec/policy, and whether an unmarked fallback was used."""
    # UTF-32 must precede UTF-16 because their little-endian BOMs overlap.
    for marker, encoding in (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
        (codecs.BOM_UTF8, "utf-8-sig"),
    ):
        if raw.startswith(marker):
            return raw.decode(encoding), encoding, False
    if html:
        # Only a bounded HTML/XML header can supply a declaration. Restrict codecs
        # to text encodings; never invoke arbitrary transform codecs from a file.
        header = b" ".join(re.findall(rb"<(?:meta\b|\?xml\b)[^>]{0,1024}>", raw[:4096], re.I))
        declared = re.search(rb"(?:charset|encoding)\s*=\s*['\"]?([a-zA-Z0-9._-]+)", header, re.I)
        if declared:
            encoding = codecs.lookup(declared[1].decode("ascii")).name
            allowed = {
                "ascii",
                "utf-8",
                "utf-8-sig",
                "iso8859-1",
                "iso8859-2",
                "iso8859-5",
                "iso8859-15",
                "cp1250",
                "cp1251",
                "cp1252",
                "koi8-r",
                "shift_jis",
                "euc_jp",
                "gb18030",
                "gbk",
                "big5",
            }
            if encoding not in allowed:
                raise ValueError(f"unsupported declared text encoding: {encoding}")
            return raw.decode(encoding), encoding, False
    try:
        return raw.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        # These single-byte encodings are ambiguous without metadata. Record the
        # fallback, tell the caller, and preserve every byte rather than replacing.
        try:
            return raw.decode("cp1252"), "cp1252", True
        except UnicodeDecodeError:
            return raw.decode("latin-1"), "iso8859-1", True
