"""CLI tests — the layer a user actually touches.

ELI5
----
Everything underneath is well covered, but the CLI is where flags get wired to
functions, and a mis-wired flag fails *silently*: the command still prints a
plausible changelog, just not the one you asked for. These tests exist to make
wrong flags loud.

`--no-github` everywhere, so the suite never touches the network.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from changelog_gen.cli import app

# Rich wraps to the terminal width; pin it so assertions aren't width-dependent.
runner = CliRunner(env={"COLUMNS": "200"})


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "changelog-gen" in result.stdout


def test_init_writes_a_config_and_refuses_to_clobber_it(tmp_path):
    path = tmp_path / ".changelog.yml"

    assert runner.invoke(app, ["init", "--path", str(path)]).exit_code == 0
    assert "tone:" in path.read_text()

    path.write_text("product: mine\n")
    clobber = runner.invoke(app, ["init", "--path", str(path)])
    assert clobber.exit_code == 1
    assert path.read_text() == "product: mine\n"  # untouched

    assert runner.invoke(app, ["init", "--path", str(path), "--force"]).exit_code == 0
    assert "tone:" in path.read_text()


def test_collect_json_reports_publishable_and_dropped(repo):
    result = runner.invoke(
        app, ["collect", "--repo", repo, "--to", "v1.1.0", "--no-github", "--json"]
    )
    assert result.exit_code == 0

    payload = json.loads(result.stdout)
    # Titles arrive cleaned: the `fix:` prefix and the trailing `(#482)` are
    # stripped by classify, because neither belongs in customer-facing prose.
    by_title = {item["title"]: item for item in payload["publishable"]}
    assert set(by_title) == {"second thing", "Add webhook retries"}
    assert by_title["second thing"]["kind"] == "fix"


def test_preview_renders_a_changelog_without_an_api_key(repo):
    result = runner.invoke(app, ["preview", "--repo", repo, "--to", "v1.1.0", "--no-github"])
    assert result.exit_code == 0
    assert "## [v1.1.0]" in result.stdout
    assert "### Bug Fixes" in result.stdout


def test_preview_show_prompt_includes_the_changes_and_the_schema(repo):
    result = runner.invoke(
        app, ["preview", "--repo", repo, "--to", "v1.1.0", "--no-github", "--show-prompt"]
    )
    assert result.exit_code == 0
    assert "source_ids" in result.stdout  # the schema made it into the prompt
    assert "estimated cost" in result.stdout


# --- flags that used to fail silently -------------------------------------


def test_unknown_style_is_rejected_rather_than_reaching_the_prompt(repo):
    """`model_copy` skips validation, so without an explicit check this wrote
    `Tone: shakespearean.` straight into the system prompt."""
    result = runner.invoke(
        app, ["generate", "--repo", repo, "--to", "v1.1.0", "--no-github", "--style", "shakespearean"]
    )
    assert result.exit_code == 2
    assert "professional" in result.stderr  # the message lists the valid tones


def test_known_style_is_accepted(repo):
    """Exit code 3 = "reached the LLM step, which isn't built yet" — i.e. the
    style was accepted. Update this once generate_notes exists."""
    result = runner.invoke(
        app, ["generate", "--repo", repo, "--to", "v1.1.0", "--no-github", "--style", "friendly"]
    )
    assert result.exit_code == 3


def test_unknown_format_is_rejected(repo):
    """`--format markdwn` used to fall through to markdown and look correct."""
    result = runner.invoke(
        app, ["generate", "--repo", repo, "--to", "v1.1.0", "--no-github", "--format", "markdwn"]
    )
    assert result.exit_code == 2
