"""Check actual source/wheel artifacts without extracting or executing their contents."""

import argparse
import tarfile
import zipfile
from pathlib import Path

DIRECTORIES = {"src", "tests", "scripts", "schemas", "examples", "docs", "deploy", ".github"}
FILES = {
    "README.md",
    "AGENTS.md",
    "pyproject.toml",
    "uv.lock",
    "setup.cmd",
    "ragforge.cmd",
    "setup.sh",
    "ragforge.sh",
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    "PKG-INFO",
}
LAUNCHERS = {"setup.cmd", "ragforge.cmd", "setup.sh", "ragforge.sh"}


def check(directory: Path) -> None:
    sources = list(directory.glob("ragforge-*.tar.gz"))
    wheels = list(directory.glob("ragforge-*.whl"))
    if len(sources) != 1 or len(wheels) != 1:
        raise ValueError("expected exactly one RAGForge source archive and wheel")
    with tarfile.open(sources[0]) as archive:
        paths = [
            Path(*Path(member.name).parts[1:]).as_posix()
            for member in archive.getmembers()
            if member.isfile()
        ]
        for name in paths:
            parts = Path(name).parts
            if not parts or (parts[0] not in DIRECTORIES and name not in FILES):
                raise ValueError(f"unexpected source archive entry: {name}")
        if not LAUNCHERS <= set(paths):
            raise ValueError("source archive is missing Windows/Linux launchers")
    with zipfile.ZipFile(wheels[0]) as wheel:
        if "ragforge/quickstart.py" not in wheel.namelist():
            raise ValueError("wheel is missing the quickstart runtime")
    print("Source/wheel verified: Windows/Linux launchers present; generated local data excluded.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    check(parser.parse_args().directory)
