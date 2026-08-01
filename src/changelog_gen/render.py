"""Turn an `LLMResponse` into Markdown — and build one *without* an LLM.

ELI5
----
Two jobs live here.

1. **Rendering.** Jinja2 templates take the validated `LLMResponse` and produce
   Keep-a-Changelog Markdown or a GitHub Release body. Templates (not f-strings)
   so the output format is a file you can edit without touching Python.

2. **`rule_based_response`** — the safety net. It builds the *same*
   `LLMResponse` shape straight from the classified changes, with no model
   involved. Two things fall out of that one function:
     * `changelog-gen preview` works with no API key at all, so you can verify
       the collector on a real repo before spending a cent.
     * When the LLM misbehaves twice in a row, the pipeline degrades to this
       instead of failing the release. A slightly rough changelog beats a red
       CI job.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from datetime import date as date_cls
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from .config import Config
from .models import ChangeItem, Entry, Kind, LLMResponse, Section

# Which bucket becomes which heading, and in what order. Breaking changes go
# first because they are the thing a reader most needs to not miss.
KIND_SECTIONS: list[tuple[Kind, str]] = [
    (Kind.BREAKING, "Breaking Changes"),
    (Kind.FEATURE, "Features"),
    (Kind.IMPROVEMENT, "Improvements"),
    (Kind.FIX, "Bug Fixes"),
]


def _env() -> Environment:
    return Environment(
        loader=PackageLoader("changelog_gen", "templates"),
        autoescape=select_autoescape(default=False, default_for_string=False),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def group_by_section(items: list[ChangeItem], config: Config) -> list[tuple[str, list[ChangeItem]]]:
    """Bucket classified items into ordered, named sections.

    Sections the user removed from `config.sections` are skipped entirely.
    """
    wanted = {name.lower() for name in config.sections}
    grouped: list[tuple[str, list[ChangeItem]]] = []
    for kind, name in KIND_SECTIONS:
        if name.lower() not in wanted:
            continue
        matching = [item for item in items if item.kind is kind]
        if matching:
            grouped.append((name, matching))
    return grouped


def rule_based_response(items: list[ChangeItem], version: str, config: Config) -> LLMResponse:
    """Build a valid LLMResponse from the raw changes, with no model call."""
    sections = [
        Section(
            name=name,
            entries=[
                Entry(text=_sentence_case(item.title), source_ids=[item.id]) for item in group
            ],
        )
        for name, group in group_by_section(items, config)
    ]
    count = sum(len(section.entries) for section in sections)
    headline = f"{count} change{'s' if count != 1 else ''} in {version}." if count else f"No customer-facing changes in {version}."
    return LLMResponse(version=version, headline=headline, sections=sections)


def _sentence_case(text: str) -> str:
    text = text.strip().rstrip(".")
    if not text:
        return text
    return text[0].upper() + text[1:] + "."


def render_markdown(
    response: LLMResponse, *, date: date_cls | None = None, show_sources: bool = True
) -> str:
    template = _env().get_template("changelog.md.j2")
    # UTC, not local time: this runs in CI as often as on a laptop, and a
    # changelog that says a different date depending on who ran it is a bug.
    return template.render(
        response=response,
        date=(date or datetime.now(UTC).date()).isoformat(),
        show_sources=show_sources,
    )


def render_github_release(response: LLMResponse, *, show_sources: bool = True) -> str:
    template = _env().get_template("github_release.md.j2")
    return template.render(response=response, show_sources=show_sources)


CHANGELOG_HEADER = """\
# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

"""


def update_changelog_file(path: Path, section_markdown: str, version: str) -> bool:
    """Insert a rendered release section at the top of CHANGELOG.md.

    Returns True if the file changed. **Idempotent**: re-running for a version
    that is already present is a no-op, which is what makes it safe to run in
    CI on every tag push (FR-6).
    """
    section = section_markdown.strip() + "\n"

    if not path.exists():
        path.write_text(CHANGELOG_HEADER + section, encoding="utf-8")
        return True

    existing = path.read_text(encoding="utf-8")
    if re.search(rf"^##\s*\[?{re.escape(version)}\]?", existing, flags=re.MULTILINE):
        return False

    lines = existing.splitlines(keepends=True)
    # Insert above the first release heading; if there is none, append to the header.
    insert_at = len(lines)
    for index, line in enumerate(lines):
        if line.startswith("## "):
            insert_at = index
            break
    updated = "".join(lines[:insert_at]).rstrip("\n") + "\n\n" + section + "\n" + "".join(lines[insert_at:])
    path.write_text(updated, encoding="utf-8")
    return True
