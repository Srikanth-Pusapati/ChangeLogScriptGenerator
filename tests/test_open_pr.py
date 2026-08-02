"""Tests for the PR helper in scripts/open_pr.py.

ELI5
----
The helper deliberately carries its own copy of the remote-URL regex, because
it must run with plain `python3` before anything is pip-installed. A copy is a
drift risk, so the first test here pins the copy to the original: if someone
teaches `collect.py` about a new remote shape and forgets the script, this
fails.

The rest cover the bit that is easy to get subtly wrong — building a URL that
GitHub actually accepts.
"""

from __future__ import annotations

import urllib.parse

import pytest

import open_pr
from changelog_gen.collect import _REMOTE_SLUG

REMOTE_URLS = [
    "https://github.com/acme/widgets.git",
    "https://github.com/acme/widgets",
    "git@github.com:acme/widgets.git",
    "ssh://git@github.com/acme/widgets.git",
    "git@github-personal:acme/widgets.git",
    "git@github-work:acme/widgets.git",
    "https://gitlab.com/acme/widgets.git",
]


@pytest.mark.parametrize("url", REMOTE_URLS)
def test_script_regex_agrees_with_the_package(url):
    """The script's copy of the regex must behave exactly like the original."""
    script = open_pr.REMOTE_SLUG.search(url)
    package = _REMOTE_SLUG.search(url)
    assert (script is None) == (package is None)
    if script and package:
        assert script.groupdict() == package.groupdict()


def test_build_url_prefills_the_github_form():
    url, body_included = open_pr.build_url(
        "acme/widgets", "feature/dev-integration", "feature/x", "My title", "Some **body**"
    )
    assert body_included
    assert url.startswith("https://github.com/acme/widgets/compare/feature/dev-integration...feature/x?")

    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    # expand=1 is what makes GitHub open the full form instead of a bare diff.
    assert query["expand"] == ["1"]
    assert query["title"] == ["My title"]
    assert query["body"] == ["Some **body**"]


def test_build_url_escapes_characters_that_would_break_the_query():
    """A title with & or # would otherwise truncate or fragment the URL."""
    url, _ = open_pr.build_url("acme/widgets", "main", "fix", "A & B #42", "")
    assert "A & B #42" not in url
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["title"] == ["A & B #42"]


def test_build_url_drops_an_oversized_body_instead_of_truncating_it():
    """Silently sending half a PR description is worse than sending none."""
    url, body_included = open_pr.build_url(
        "acme/widgets", "main", "fix", "t", "x" * (open_pr.MAX_URL_LEN + 1)
    )
    assert not body_included
    assert "body=" not in url
    assert len(url) < open_pr.MAX_URL_LEN
