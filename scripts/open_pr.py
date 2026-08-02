#!/usr/bin/env python3
"""Open a GitHub pull request from the terminal — without the `gh` CLI.

ELI5
----
`git` can push a branch, but it cannot create a pull request: a PR is a GitHub
concept, not a git one. Normally you'd use `gh pr create`, but `gh` on this
machine is authenticated as a different GitHub account (reserved for other
work), and it has no write access here.

So this script uses the one PR path that needs no extra credentials at all:
GitHub's **compare URL**. Pushing uses your SSH key, exactly like every other
`git push`; then we open

    https://github.com/OWNER/REPO/compare/BASE...HEAD?expand=1&title=…&body=…

which is the normal "Open a pull request" form with the title and body already
filled in. You read it and press the green button. One click, no tokens.

Usage
-----
    python3 scripts/open_pr.py                          # sensible defaults
    python3 scripts/open_pr.py --body-file notes.md
    python3 scripts/open_pr.py --base main --print-only

Defaults: base is `feature/dev-integration`, head is the current branch, and
the body is generated from the commits that branch adds.

Stdlib only, on purpose — opening a PR shouldn't depend on the virtualenv
being active or on `pip install` having been run.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

DEFAULT_BASE = "feature/dev-integration"

# Mirrors `_REMOTE_SLUG` in src/changelog_gen/collect.py — the host only has to
# *contain* "github", so SSH host aliases (git@github-personal:owner/repo.git)
# work too. tests/test_open_pr.py asserts the two stay in agreement.
REMOTE_SLUG = re.compile(
    r"github[^/:]*[:/](?P<owner>[^/:]+)/(?P<name>[^/]+?)(?:\.git)?/?$", re.IGNORECASE
)

# GitHub truncates very long querystrings, and browsers have their own limits.
# Well under both; past this we hand the body over via the clipboard instead.
MAX_URL_LEN = 6000


class PrError(RuntimeError):
    """Anything that should stop us with a readable message, not a traceback."""


def git(*args: str, cwd: str | None = None) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise PrError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def repo_slug(remote: str = "origin", cwd: str | None = None) -> str:
    """Turn the remote URL into "owner/name"."""
    url = git("remote", "get-url", remote, cwd=cwd)
    match = REMOTE_SLUG.search(url)
    if not match:
        raise PrError(
            f"Could not read a GitHub owner/repo out of the {remote} remote:\n  {url}\n"
            "Pass --slug owner/name to override."
        )
    return f"{match.group('owner')}/{match.group('name')}"


def current_branch(cwd: str | None = None) -> str:
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    if branch == "HEAD":
        raise PrError("You are in a detached HEAD state. Check out a branch first.")
    return branch


def default_body(base: str, head: str, cwd: str | None = None) -> str:
    """A starting body: the commits this branch adds on top of the base.

    Deliberately plain. It's a draft you edit in the GitHub form before
    submitting, not a finished PR description.
    """
    try:
        log = git("log", f"origin/{base}..{head}", "--reverse", "--pretty=- %s", cwd=cwd)
    except PrError:
        log = git("log", f"{base}..{head}", "--reverse", "--pretty=- %s", cwd=cwd)
    return f"## Commits\n\n{log}\n" if log else ""


def build_url(slug: str, base: str, head: str, title: str, body: str) -> tuple[str, bool]:
    """Return `(url, body_included)`.

    `body_included` is False when the body was too long to put in the
    querystring — the caller then routes it via the clipboard.
    """
    stem = f"https://github.com/{slug}/compare/{urllib.parse.quote(base)}...{urllib.parse.quote(head)}"
    params = {"expand": "1", "title": title}
    with_body = f"{stem}?{urllib.parse.urlencode({**params, 'body': body})}"
    if len(with_body) <= MAX_URL_LEN:
        return with_body, True
    return f"{stem}?{urllib.parse.urlencode(params)}", False


def copy_to_clipboard(text: str) -> bool:
    for cmd in (["pbcopy"], ["xclip", "-selection", "clipboard"], ["wl-copy"]):
        try:
            subprocess.run(cmd, input=text, text=True, check=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return False


def open_in_browser(url: str) -> bool:
    for cmd in (["open"], ["xdg-open"]):
        try:
            subprocess.run([*cmd, url], check=True, capture_output=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Push the current branch and open a pre-filled GitHub PR form.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"target branch (default: {DEFAULT_BASE})")
    parser.add_argument("--head", default=None, help="source branch (default: current branch)")
    parser.add_argument("--title", default=None, help="PR title (default: last commit subject)")
    parser.add_argument("--body-file", default=None, help="path to a Markdown PR body")
    parser.add_argument("--slug", default=None, help='override "owner/name"')
    parser.add_argument("--no-push", action="store_true", help="skip `git push`")
    parser.add_argument("--print-only", action="store_true", help="print the URL, don't open it")
    args = parser.parse_args(argv)

    try:
        root = git("rev-parse", "--show-toplevel")
        head = args.head or current_branch(root)
        base = args.base

        if head == base:
            raise PrError(f"head and base are both '{head}' — nothing to compare.")
        if head in {"main", "master"}:
            raise PrError(
                f"Refusing to open a PR *from* '{head}'. Work happens on a feature "
                "branch; see PROGRESS.md."
            )

        slug = args.slug or repo_slug(cwd=root)

        dirty = git("status", "--porcelain", cwd=root)
        if dirty:
            print("! Uncommitted changes — these will NOT be in the PR:", file=sys.stderr)
            print(dirty, file=sys.stderr)

        if not args.no_push:
            print(f"→ pushing {head} to origin…")
            subprocess.run(["git", "push", "-u", "origin", head], cwd=root, check=True)

        title = args.title or git("log", "-1", "--pretty=%s", head, cwd=root)
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        else:
            body = default_body(base, head, cwd=root)

        url, body_included = build_url(slug, base, head, title, body)

        print(f"\n  {slug}:  {head}  →  {base}")
        print(f"  title:  {title}\n")

        if not body_included:
            copied = copy_to_clipboard(body)
            where = "copied to your clipboard — paste it" if copied else "shown above"
            print(f"! Body too long for a URL ({len(body)} chars); it is {where}.\n")

        print(url)
        if not args.print_only and not open_in_browser(url):
            print("\n(Could not launch a browser — open the URL above.)", file=sys.stderr)
    except PrError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"error: command failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
