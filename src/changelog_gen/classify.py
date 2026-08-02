"""Decide which bucket each change belongs in — with rules, not an LLM.

ELI5
----
"Is this a feature or a bug fix?" is answerable ~90% of the time by looking at
the Conventional Commit prefix (`feat:`, `fix:`) or the PR label (`bug`,
`enhancement`). Rules are free, instant and deterministic, so we do that first
and only ever consider spending tokens on the leftovers.

This is the single most important design idea in the project: **do the boring
part with code, and give the LLM the one job code can't do** (writing prose a
customer wants to read).

Order of precedence, strongest signal first:
  1. explicit breaking markers  (`feat!:`, `BREAKING CHANGE:`, a breaking label)
  2. PR labels                  (mapped via config.label_map, then defaults)
  3. Conventional Commit prefix (`feat` -> feature, `chore` -> internal, ...)
  4. fallback                   -> improvement
"""

from __future__ import annotations

import re
from fnmatch import fnmatch

from .config import Config
from .models import ChangeItem, Kind

# type(scope)!: subject
CONVENTIONAL = re.compile(
    r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<subject>.+)$"
)

PREFIX_KIND: dict[str, Kind] = {
    "feat": Kind.FEATURE,
    "feature": Kind.FEATURE,
    "fix": Kind.FIX,
    "bugfix": Kind.FIX,
    "hotfix": Kind.FIX,
    "revert": Kind.FIX,
    "perf": Kind.IMPROVEMENT,
    "refactor": Kind.IMPROVEMENT,
    "style": Kind.INTERNAL,
    "docs": Kind.INTERNAL,
    "doc": Kind.INTERNAL,
    "test": Kind.INTERNAL,
    "tests": Kind.INTERNAL,
    "chore": Kind.INTERNAL,
    "ci": Kind.INTERNAL,
    "build": Kind.INTERNAL,
    "deps": Kind.INTERNAL,
    "release": Kind.INTERNAL,
}

LABEL_KIND: dict[str, Kind] = {
    "feature": Kind.FEATURE,
    "feat": Kind.FEATURE,
    "new feature": Kind.FEATURE,
    "enhancement": Kind.IMPROVEMENT,
    "improvement": Kind.IMPROVEMENT,
    "performance": Kind.IMPROVEMENT,
    "bug": Kind.FIX,
    "bugfix": Kind.FIX,
    "fix": Kind.FIX,
    "documentation": Kind.INTERNAL,
    "docs": Kind.INTERNAL,
    "chore": Kind.INTERNAL,
    "dependencies": Kind.INTERNAL,
    "internal": Kind.INTERNAL,
    "ci": Kind.INTERNAL,
}

BREAKING_BODY = re.compile(r"^BREAKING[ -]CHANGE:", re.MULTILINE | re.IGNORECASE)


def parse_conventional(title: str) -> tuple[str | None, bool, str]:
    """Return `(type, is_breaking, subject_without_prefix)`.

    Degrades gracefully: a title with no prefix returns `(None, False, title)`,
    which is exactly what most real-world repos look like.
    """
    match = CONVENTIONAL.match(title.strip())
    if not match:
        return None, False, title.strip()
    return (
        match.group("type").lower(),
        bool(match.group("bang")),
        match.group("subject").strip(),
    )


def is_breaking(item: ChangeItem, config: Config) -> bool:
    _, bang, _ = parse_conventional(item.title)
    if bang:
        return True
    if item.body and BREAKING_BODY.search(item.body):
        return True
    breaking_labels = {label.lower() for label in config.breaking_labels}
    return any(label.lower() in breaking_labels for label in item.labels)


def should_ignore(item: ChangeItem, config: Config) -> bool:
    """Glob-match the raw title against `config.ignore`."""
    title = item.title.strip()
    return any(fnmatch(title, pattern) for pattern in config.ignore)


def kind_for(item: ChangeItem, config: Config) -> Kind:
    if is_breaking(item, config):
        return Kind.BREAKING

    # PR labels beat commit prefixes: a human chose them on purpose.
    custom = {k.lower(): v for k, v in config.label_map.items()}
    for label in item.labels:
        key = label.lower()
        if key in custom:
            try:
                return Kind(custom[key])
            except ValueError:
                continue  # unknown value in config; ignore rather than crash
        if key in LABEL_KIND:
            return LABEL_KIND[key]

    prefix, _, _ = parse_conventional(item.title)
    if prefix and prefix in PREFIX_KIND:
        return PREFIX_KIND[prefix]

    # No signal at all. "improvement" is the safe default: it reads fine in a
    # changelog and the LLM sees the raw title anyway.
    return Kind.IMPROVEMENT


def clean_title(title: str) -> str:
    """Strip the Conventional prefix and any trailing "(#123)"."""
    _, _, subject = parse_conventional(title)
    return re.sub(r"\s*\(#\d+\)\s*$", "", subject).strip()


def classify_all(items: list[ChangeItem], config: Config) -> tuple[list[ChangeItem], list[ChangeItem]]:
    """Classify everything. Returns `(publishable, dropped)`.

    We return the dropped items too, so `--verbose` can show what was filtered
    out. Silent filtering is how you ship a changelog missing the one thing the
    customer cared about.
    """
    publishable: list[ChangeItem] = []
    dropped: list[ChangeItem] = []

    for item in items:
        kind = kind_for(item, config)
        classified = item.model_copy(update={"kind": kind, "title": clean_title(item.title)})
        if should_ignore(item, config) or kind is Kind.INTERNAL:
            dropped.append(classified)
        else:
            publishable.append(classified)

    return publishable, dropped
