"""Collector tests. These run against a real, tiny git repo built in a tmpdir.

The `repo` fixture lives in conftest.py — the CLI tests use it too.

The GitHub half is tested with a fake `requests.Session`, so the suite never
touches the network.
"""

from __future__ import annotations

import subprocess

import pytest

from changelog_gen.collect import (
    _dedupe,
    collect_commits,
    commit_pr_number,
    detect_repo_slug,
    previous_tag,
)
from changelog_gen.models import ChangeItem


def test_collect_commits_parses_subject_body_and_author(repo):
    items = collect_commits("v1.0.0", "v1.1.0", repo)
    titles = [item.title for item in items]

    assert "fix: second thing" in titles
    assert "Add webhook retries (#482)" in titles
    assert all(item.source == "commit" for item in items)
    assert all(item.author == "Test" for item in items)

    fix = next(item for item in items if item.title.startswith("fix:"))
    assert fix.body is not None and "Body line here." in fix.body
    assert "#42" in fix.refs


def test_previous_tag(repo):
    assert previous_tag("v1.1.0", repo) == "v1.0.0"
    assert previous_tag("v1.0.0", repo) is None


def test_detect_repo_slug(repo):
    assert detect_repo_slug(repo) == "acme/widgets"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/acme/widgets.git", "acme/widgets"),
        ("https://github.com/acme/widgets", "acme/widgets"),
        ("git@github.com:acme/widgets.git", "acme/widgets"),
        ("ssh://git@github.com/acme/widgets.git", "acme/widgets"),
        # SSH host alias from ~/.ssh/config — common when you juggle two
        # GitHub accounts. Matching only "github.com" silently breaks these.
        ("git@github-personal:acme/widgets.git", "acme/widgets"),
        ("git@github-work:acme/widgets.git", "acme/widgets"),
        ("https://gitlab.com/acme/widgets.git", None),
    ],
)
def test_detect_repo_slug_url_shapes(tmp_path, url, expected):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", url], cwd=tmp_path, check=True, capture_output=True)
    assert detect_repo_slug(str(tmp_path)) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Add webhook retries (#482)", 482),
        ("Merge pull request #77 from acme/feature", 77),
        ("fix: something with #42 in the middle", None),
        ("no pr here", None),
    ],
)
def test_commit_pr_number(title, expected):
    assert commit_pr_number(title) == expected


def test_dedupe_prefers_the_pr_over_its_squash_commit():
    """The whole point: a PR carries a title, body and labels; the commit doesn't."""
    commits = [
        ChangeItem(id="aaa111", source="commit", title="Add webhook retries (#482)"),
        ChangeItem(id="bbb222", source="commit", title="Fix a typo"),
    ]
    prs = [ChangeItem(id="#482", source="pr", title="Add webhook retries", labels=["feature"])]

    merged = _dedupe(commits, prs)

    assert [item.id for item in merged] == ["#482", "bbb222"]
