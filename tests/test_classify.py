"""Classifier tests, driven by a corpus of *ugly real-world* commit messages.

ELI5
----
Grow this list every time you see a commit message that classifies badly. It
costs nothing and it becomes your eval set later — the same corpus you'll use
to check whether a prompt change made output better or worse.
"""

from __future__ import annotations

import pytest

from changelog_gen.classify import classify_all, clean_title, kind_for, parse_conventional
from changelog_gen.config import Config
from changelog_gen.models import ChangeItem, Kind


def commit(title: str, **kwargs) -> ChangeItem:
    return ChangeItem(id=kwargs.pop("id", "abc123"), source="commit", title=title, **kwargs)


def pr(title: str, number: int = 1, **kwargs) -> ChangeItem:
    return ChangeItem(id=f"#{number}", source="pr", title=title, **kwargs)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("feat: add CSV export", ("feat", False, "add CSV export")),
        ("feat(api)!: drop v1 endpoints", ("feat", True, "drop v1 endpoints")),
        ("fix(webhooks): retry on 502", ("fix", False, "retry on 502")),
        ("FIX: shouty prefix", ("fix", False, "shouty prefix")),
        ("just a plain message", (None, False, "just a plain message")),
        ("WIP", (None, False, "WIP")),
        ("update: notes", ("update", False, "notes")),
    ],
)
def test_parse_conventional(title, expected):
    assert parse_conventional(title) == expected


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (commit("feat: add CSV export"), Kind.FEATURE),
        (commit("fix: null check in retry loop"), Kind.FIX),
        (commit("perf: cache the tag lookup"), Kind.IMPROVEMENT),
        (commit("chore: bump deps"), Kind.INTERNAL),
        (commit("ci: pin runner image"), Kind.INTERNAL),
        (commit("docs: fix typo in README"), Kind.INTERNAL),
        (commit("feat!: rename the config key"), Kind.BREAKING),
        (commit("wip"), Kind.IMPROVEMENT),  # no signal -> safe default
        (commit("fix", body="BREAKING CHANGE: config format changed"), Kind.BREAKING),
        (pr("Add dark mode", labels=["enhancement"]), Kind.IMPROVEMENT),
        (pr("Stop dropping webhooks", labels=["bug"]), Kind.FIX),
        (pr("Remove v1 API", labels=["breaking-change"]), Kind.BREAKING),
        (pr("Speed up export", labels=["performance"]), Kind.IMPROVEMENT),
    ],
)
def test_kind_for(item, expected):
    assert kind_for(item, Config()) is expected


def test_labels_beat_prefixes():
    """A human-chosen label outranks a prefix someone typed from muscle memory."""
    item = pr("chore: actually a user-visible feature", labels=["feature"])
    assert kind_for(item, Config()) is Kind.FEATURE


def test_custom_label_map():
    config = Config(label_map={"needs-release-note": "feature"})
    assert kind_for(pr("Something", labels=["needs-release-note"]), config) is Kind.FEATURE


def test_unknown_label_map_value_does_not_crash():
    config = Config(label_map={"weird": "not-a-kind"})
    assert kind_for(pr("Something", labels=["weird"]), config) is Kind.IMPROVEMENT


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("feat: add CSV export (#482)", "add CSV export"),
        ("fix(api): handle 429", "handle 429"),
        ("Plain title (#12)", "Plain title"),
    ],
)
def test_clean_title(title, expected):
    assert clean_title(title) == expected


def test_classify_all_splits_publishable_from_dropped():
    items = [
        commit("feat: add export", id="aaa"),
        commit("chore: bump deps", id="bbb"),
        commit("bump version to 1.4.0", id="ccc"),  # matches an ignore glob
        pr("Fix the webhook retry", number=7, labels=["bug"]),
    ]
    publishable, dropped = classify_all(items, Config())

    assert [item.id for item in publishable] == ["aaa", "#7"]
    assert {item.id for item in dropped} == {"bbb", "ccc"}
    assert publishable[0].title == "add export"  # prefix stripped
