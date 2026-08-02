from __future__ import annotations

from changelog_gen.config import Config
from changelog_gen.models import ChangeItem, Entry, Kind, LLMResponse, Section
from changelog_gen.render import (
    group_by_section,
    render_github_release,
    render_markdown,
    rule_based_response,
    update_changelog_file,
)


def item(item_id: str, kind: Kind, title: str) -> ChangeItem:
    return ChangeItem(id=item_id, source="pr", title=title, kind=kind)


ITEMS = [
    item("#1", Kind.FEATURE, "CSV export"),
    item("#2", Kind.FIX, "Webhooks retry reliably"),
    item("#3", Kind.BREAKING, "Removed the v1 API"),
]


def test_group_by_section_puts_breaking_first():
    grouped = group_by_section(ITEMS, Config())
    assert [name for name, _ in grouped] == ["Breaking Changes", "Features", "Bug Fixes"]


def test_group_by_section_honours_config_sections():
    config = Config(sections=["Features"])
    grouped = group_by_section(ITEMS, config)
    assert [name for name, _ in grouped] == ["Features"]


def test_rule_based_response_is_a_valid_llm_response():
    """The fallback must satisfy exactly the same contract as the model's output."""
    response = rule_based_response(ITEMS, "v1.4.0", Config())

    assert response.version == "v1.4.0"
    assert "3 changes" in response.headline
    assert set(response.all_source_ids()) == {"#1", "#2", "#3"}
    LLMResponse.model_validate(response.model_dump())  # round-trips cleanly


def test_render_markdown_shape():
    response = LLMResponse(
        version="v1.4.0",
        headline="A small but useful release.",
        sections=[Section(name="Features", entries=[Entry(text="Export as CSV.", source_ids=["#1"])])],
    )
    out = render_markdown(response, show_sources=True)

    assert out.startswith("## [v1.4.0] - ")
    assert "A small but useful release." in out
    assert "### Features" in out
    assert "- Export as CSV. (#1)" in out


def test_render_github_release_omits_version_heading():
    response = LLMResponse(
        version="v1.4.0",
        headline="Headline.",
        sections=[Section(name="Bug Fixes", entries=[Entry(text="Fixed it.", source_ids=["#2"])])],
    )
    out = render_github_release(response)

    assert "## [v1.4.0]" not in out
    assert "## Bug Fixes" in out
    assert "* Fixed it. (#2)" in out


def test_update_changelog_file_is_idempotent(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    response = rule_based_response(ITEMS, "v1.4.0", Config())
    section = render_markdown(response)

    assert update_changelog_file(path, section, "v1.4.0") is True
    first = path.read_text()

    # Re-running the exact same release must not duplicate the section.
    assert update_changelog_file(path, section, "v1.4.0") is False
    assert path.read_text() == first


def test_update_changelog_file_prepends_newer_releases(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    config = Config()

    update_changelog_file(path, render_markdown(rule_based_response(ITEMS, "v1.4.0", config)), "v1.4.0")
    update_changelog_file(path, render_markdown(rule_based_response(ITEMS, "v1.5.0", config)), "v1.5.0")

    text = path.read_text()
    assert text.index("[v1.5.0]") < text.index("[v1.4.0]")
