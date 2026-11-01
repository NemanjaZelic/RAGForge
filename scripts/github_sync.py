"""Explicit maintenance tool. Never imported by the offline retrieval runtime.

Uses Git's configured credential helper without printing/storing credentials.
No new tokens or persistent permissions are created. Pushes are never forced.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=90,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"},
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"git {args[0]} failed; check Git authentication and repository access")
    return result.stdout.strip()


def credential() -> str:
    result = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"},
    )
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    token = values.get("password")
    if result.returncode or not token:
        raise RuntimeError(
            "No saved GitHub credential is available to Git; use the prepared browser form"
        )
    return token


def api(token: str, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://api.github.com" + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "RAGForge-git-setup",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        value: dict[str, Any] = json.load(response)
        return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a private GitHub repo; optionally create and push."
    )
    parser.add_argument("--owner", default="NemanjaZelic")
    parser.add_argument("--repo", default="RAGForge")
    parser.add_argument(
        "--open", action="store_true", help="Open the prefilled private repository form"
    )
    parser.add_argument(
        "--create", action="store_true", help="Create an empty private repo if it does not exist"
    )
    parser.add_argument(
        "--push", action="store_true", help="Verify privacy, set origin if absent, and push main"
    )
    args = parser.parse_args()
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", item) for item in (args.owner, args.repo)):
        parser.error("invalid GitHub owner or repository name")
    form = "https://github.com/new?" + urllib.parse.urlencode(
        {
            "owner": args.owner,
            "name": args.repo,
            "visibility": "private",
            "description": "Portable local document retrieval for agents",
        }
    )
    if args.open:
        webbrowser.open(form, new=2)
    print(f"Prepared private repository form: {form}")
    if not args.create and not args.push:
        return 0
    try:
        if git("branch", "--show-current") != "main":
            raise RuntimeError("Switch to main before synchronizing")
        if git("status", "--porcelain"):
            raise RuntimeError("Commit or review outstanding changes before synchronizing")
        token = credential()
        profile = api(token, "/user")
        if profile.get("login", "").casefold() != args.owner.casefold():
            raise RuntimeError("Saved Git credential belongs to a different GitHub account")
        full_name = f"{args.owner}/{args.repo}"
        remote = f"https://github.com/{full_name}.git"
        remotes = git("remote").splitlines()
        if "origin" in remotes and git("remote", "get-url", "origin") != remote:
            raise RuntimeError("Existing origin differs; it will not be overwritten")
        try:
            repo = api(token, f"/repos/{full_name}")
            if "origin" not in remotes and repo.get("size", 0) != 0:
                raise RuntimeError(
                    "Repository name is already used by a nonempty repo; choose a new name"
                )
        except urllib.error.HTTPError as error:
            if error.code != 404 or not args.create:
                raise
            repo = api(
                token,
                "/user/repos",
                {
                    "name": args.repo,
                    "private": True,
                    "auto_init": False,
                    "description": "Portable local document retrieval for agents",
                },
            )
        if repo.get("private") is not True or repo.get("visibility") != "private":
            raise RuntimeError("Repository is not private; refusing to upload any code")
        if repo.get("full_name", "").casefold() != full_name.casefold():
            raise RuntimeError("Unexpected repository identity; refusing to upload")
        print(f"Verified private repository: https://github.com/{full_name}")
        if args.push:
            if "origin" not in remotes:
                git("remote", "add", "origin", remote)
            git("push", "--set-upstream", "origin", "main")
            local = git("rev-parse", "HEAD")
            published = git("ls-remote", "origin", "refs/heads/main").split()
            if not published or local != published[0]:
                raise RuntimeError("Remote main does not match local HEAD")
            print(f"Saved and verified main at {local}")
        return 0
    except urllib.error.HTTPError as error:
        print(
            f"GitHub API HTTP {error.code}. Complete the prepared form, then rerun --push.",
            file=sys.stderr,
        )
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        # urllib URLError and timeout messages contain no request headers or credentials.
        print(str(error), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
