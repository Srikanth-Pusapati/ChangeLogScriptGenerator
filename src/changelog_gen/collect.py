"""Gather the raw facts: commits from `git`, merged PRs from the GitHub API.

ELI5
----
This module answers one question: *what changed between v1.3.0 and v1.4.0?*

It does it twice, from two sources, because neither alone is good enough:

  * `git log` always works (no network, no token) but commit messages are
    often terrible ("fix", "wip", "address review").
  * The GitHub API gives you PR titles, bodies and labels — usually much better
    written, because a human wrote them for other humans.

Then it de-duplicates: a squash-merge produces a commit titled
"Add webhook retries (#482)" *and* a PR #482. We keep the PR and drop the
commit, because the PR carries more context.

Nothing here talks to an LLM. This is the "deterministic shell".
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime

import requests

from .models import ChangeItem

# Field/record separators that will never appear in a commit message.
_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"
_GIT_FORMAT = _FIELD_SEP.join(["%H", "%h", "%s", "%an", "%b"]) + _RECORD_SEP

# "Add webhook retries (#482)"  ->  482
_TRAILING_PR = re.compile(r"\(#(\d+)\)\s*$")
# "Merge pull request #482 from acme/webhooks"  ->  482
_MERGE_PR = re.compile(r"^Merge pull request #(\d+)\b")
# Any "#123" mention, used to link issues.
_ISSUE_REF = re.compile(r"#(\d+)")

GITHUB_API = "https://api.github.com"


class CollectError(RuntimeError):
    """Something went wrong talking to git or GitHub."""


@dataclass
class Repo:
    """A local git checkout, plus its GitHub identity if we can work it out."""

    path: str = "."
    slug: str | None = None  # "owner/name"


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def _git(args: list[str], repo_path: str = ".") -> str:
    """Run a git command and return stdout, or raise CollectError."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # git not installed
        raise CollectError("git is not installed or not on PATH") from exc
    if proc.returncode != 0:
        raise CollectError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def previous_tag(ref: str, repo_path: str = ".") -> str | None:
    """The tag immediately before `ref`, so `--from` can be optional.

    `git describe --tags --abbrev=0 <ref>^` = "the nearest tag reachable from
    the parent of ref". Returns None on the very first release.
    """
    try:
        return _git(["describe", "--tags", "--abbrev=0", f"{ref}^"], repo_path).strip() or None
    except CollectError:
        return None


def ref_datetime(ref: str, repo_path: str = ".") -> datetime | None:
    """Commit date of `ref` in ISO-8601, used to window the GitHub PR query."""
    try:
        raw = _git(["log", "-1", "--format=%cI", ref], repo_path).strip()
    except CollectError:
        return None
    if not raw:
        return None
    return datetime.fromisoformat(raw)


# Matches the shapes a GitHub remote actually takes in the wild:
#   https://github.com/owner/repo.git
#   git@github.com:owner/repo.git
#   ssh://git@github.com/owner/repo.git
#   git@github-personal:owner/repo.git   <- an SSH host alias from ~/.ssh/config
# The host only has to *contain* "github", which is what makes aliases work.
_REMOTE_SLUG = re.compile(
    r"github[^/:]*[:/](?P<owner>[^/:]+)/(?P<name>[^/]+?)(?:\.git)?/?$", re.IGNORECASE
)


def detect_repo_slug(repo_path: str = ".") -> str | None:
    """Turn the `origin` remote into "owner/name", or None if we can't tell.

    People with several GitHub accounts commonly use an SSH host alias
    (`git@github-personal:me/repo.git`) so each remote picks up a different
    key. Matching only the literal string "github.com" silently breaks for
    them — the tool degrades to commits-only and never says why.
    """
    try:
        url = _git(["remote", "get-url", "origin"], repo_path).strip()
    except CollectError:
        return None
    match = _REMOTE_SLUG.search(url)
    if not match:
        return None
    return f"{match.group('owner')}/{match.group('name')}"


def collect_commits(from_ref: str | None, to_ref: str, repo_path: str = ".") -> list[ChangeItem]:
    """Every non-merge commit in `from_ref..to_ref` as ChangeItems.

    `--no-merges` drops "Merge pull request #N" noise; we pick the PRs up from
    the API instead, where they carry a title and body worth reading.
    """
    rev_range = f"{from_ref}..{to_ref}" if from_ref else to_ref
    raw = _git(["log", rev_range, "--no-merges", f"--pretty=format:{_GIT_FORMAT}"], repo_path)

    items: list[ChangeItem] = []
    for record in raw.split(_RECORD_SEP):
        record = record.strip("\n")
        if not record.strip():
            continue
        parts = record.split(_FIELD_SEP)
        if len(parts) < 5:
            continue
        _full_sha, short_sha, subject, author, body = parts[0], parts[1], parts[2], parts[3], parts[4]
        items.append(
            ChangeItem(
                id=short_sha,
                source="commit",
                title=subject.strip(),
                body=(body.strip() or None),
                author=author.strip() or None,
                refs=_extract_refs(subject, body),
            )
        )
    return items


def commit_pr_number(title: str) -> int | None:
    """PR number embedded in a commit subject, if any."""
    for pattern in (_TRAILING_PR, _MERGE_PR):
        match = pattern.search(title)
        if match:
            return int(match.group(1))
    return None


def _extract_refs(*texts: str | None) -> list[str]:
    """Collect distinct "#123" issue references, preserving first-seen order."""
    seen: list[str] = []
    for text in texts:
        if not text:
            continue
        for num in _ISSUE_REF.findall(text):
            ref = f"#{num}"
            if ref not in seen:
                seen.append(ref)
    return seen


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


def github_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def collect_prs(
    slug: str,
    since: datetime | None,
    until: datetime | None,
    *,
    token: str | None = None,
    session: requests.Session | None = None,
    max_pages: int = 10,
) -> list[ChangeItem]:
    """Merged PRs whose merge time falls in (since, until].

    GitHub has no "list PRs merged between two dates" endpoint, so we page
    through closed PRs newest-updated-first and stop once we're clearly past
    the window. `max_pages` bounds the worst case.
    """
    http = session or requests.Session()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    items: list[ChangeItem] = []
    for page in range(1, max_pages + 1):
        response = http.get(
            f"{GITHUB_API}/repos/{slug}/pulls",
            headers=headers,
            params={
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": 100,
                "page": page,
            },
            timeout=30,
        )
        if response.status_code == 404:
            raise CollectError(f"GitHub repo {slug} not found (private repo without a token?)")
        if response.status_code == 401:
            raise CollectError("GitHub rejected the token (GITHUB_TOKEN invalid or expired)")
        if response.status_code == 403:
            raise CollectError("GitHub rate limit hit — set GITHUB_TOKEN to raise it")
        response.raise_for_status()

        payload = response.json()
        if not payload:
            break

        stop = False
        for pr in payload:
            merged_at = pr.get("merged_at")
            if not merged_at:
                continue  # closed but never merged
            # Python 3.11+ parses the trailing "Z" natively; no replace needed.
            merged = datetime.fromisoformat(merged_at)
            if until and merged > until:
                continue
            if since and merged <= since:
                # Sorted by *updated*, not merged, so keep scanning this page but
                # note that we're deep enough to stop after it.
                stop = True
                continue
            items.append(_pr_to_item(pr))
        if stop or len(payload) < 100:
            break
    return items


def _pr_to_item(pr: dict) -> ChangeItem:
    body = (pr.get("body") or "").strip() or None
    return ChangeItem(
        id=f"#{pr['number']}",
        source="pr",
        title=(pr.get("title") or "").strip(),
        body=body,
        labels=[label["name"] for label in pr.get("labels", [])],
        author=(pr.get("user") or {}).get("login"),
        url=pr.get("html_url"),
        refs=_extract_refs(pr.get("title"), body),
    )


# ---------------------------------------------------------------------------
# The one function the CLI actually calls
# ---------------------------------------------------------------------------


def collect(
    to_ref: str,
    from_ref: str | None = None,
    *,
    repo_path: str = ".",
    use_github: bool = True,
    token: str | None = None,
    session: requests.Session | None = None,
    slug: str | None = None,
) -> tuple[list[ChangeItem], list[str]]:
    """Collect commits + PRs for a release. Returns `(items, warnings)`.

    Warnings are non-fatal: "couldn't reach GitHub" should degrade to a
    commits-only changelog, not kill the run.
    """
    warnings: list[str] = []
    resolved_from = from_ref or previous_tag(to_ref, repo_path)
    if resolved_from is None:
        warnings.append(f"No previous tag found before {to_ref}; collecting full history.")

    commits = collect_commits(resolved_from, to_ref, repo_path)

    prs: list[ChangeItem] = []
    if use_github:
        slug = slug or detect_repo_slug(repo_path)
        if slug is None:
            warnings.append(
                "Could not detect a GitHub 'origin' remote; using commits only. "
                "Set `github_repo: owner/name` in .changelog.yml to override."
            )
        else:
            since = ref_datetime(resolved_from, repo_path) if resolved_from else None
            until = ref_datetime(to_ref, repo_path)
            try:
                prs = collect_prs(
                    slug, since, until, token=token or github_token(), session=session
                )
            except (CollectError, requests.RequestException) as exc:
                warnings.append(f"GitHub lookup failed ({exc}); using commits only.")

    return _dedupe(commits, prs), warnings


def _dedupe(commits: list[ChangeItem], prs: list[ChangeItem]) -> list[ChangeItem]:
    """Drop commits that are just the squash-merge of a PR we already have."""
    pr_ids = {pr.id for pr in prs}
    kept = [c for c in commits if _pr_id_for(c) not in pr_ids]
    return [*prs, *kept]


def _pr_id_for(commit: ChangeItem) -> str | None:
    number = commit_pr_number(commit.title)
    return f"#{number}" if number is not None else None
