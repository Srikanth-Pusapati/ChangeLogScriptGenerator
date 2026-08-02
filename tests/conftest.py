"""Shared fixtures.

ELI5
----
Mocking `git` would test our mock, not our parsing. Building three real commits
in a temp directory takes milliseconds and exercises the thing that actually
breaks: `--pretty=format:` parsing and tag discovery.

This fixture lives here (rather than in one test file) because both the
collector tests and the CLI tests need the same throwaway repo.
"""

from __future__ import annotations

import subprocess

import pytest


@pytest.fixture
def repo(tmp_path):
    """A tiny git repo: two tags, a squash-merge-shaped commit, a body with #42."""

    def run(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    run("init", "-b", "main")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    run("remote", "add", "origin", "git@github.com:acme/widgets.git")

    (tmp_path / "a.txt").write_text("a")
    run("add", ".")
    run("commit", "-m", "feat: first feature")
    run("tag", "v1.0.0")

    (tmp_path / "b.txt").write_text("b")
    run("add", ".")
    run("commit", "-m", "fix: second thing\n\nBody line here.\nCloses #42")

    (tmp_path / "c.txt").write_text("c")
    run("add", ".")
    run("commit", "-m", "Add webhook retries (#482)")
    run("tag", "v1.1.0")

    return str(tmp_path)
