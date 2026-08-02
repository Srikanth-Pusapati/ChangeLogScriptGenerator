"""The command-line front door.

ELI5
----
The CLI is a *thin adapter*. It parses flags, calls the pipeline, prints the
result. Every command here is a handful of lines because all the real work
lives in importable functions — which is what will let the same core power the
GitHub Action (Phase 2) and the hosted app (Phase 4) without a rewrite.

Commands, in the order you'll use them while building:

  init      write a starter .changelog.yml
  collect   dump the raw ChangeItems as JSON      <- verify the collector first
  preview   rule-based changelog, no API key      <- verify the classifier next
  generate  the full LLM pipeline                 <- your next build session
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import get_args

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .classify import classify_all
from .collect import CollectError, collect, previous_tag
from .config import EXAMPLE_CONFIG, Config, load_config
from .llm import build_system_prompt, build_user_prompt, estimate_cost
from .render import (
    render_github_release,
    render_markdown,
    rule_based_response,
    update_changelog_file,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Turn Git commits and merged PRs into publishable release notes.",
)
console = Console()
err = Console(stderr=True)


class OutputFormat(str, Enum):
    """Render targets for `generate --format`.

    An Enum rather than a plain `str` so Typer rejects typos itself. With a
    bare string, `--format markdwn` silently fell through to markdown — the
    output looked fine, so you'd never know the flag hadn't taken effect.
    """

    markdown = "markdown"
    release = "release"
    json = "json"


# The valid tones are declared once, as a Literal on Config. Reading them back
# out means `--style` can never drift from what .changelog.yml accepts.
TONES: tuple[str, ...] = get_args(Config.model_fields["tone"].annotation)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"changelog-gen {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """AI-powered changelog generator."""


def _load(config_path: Path | None, repo: str) -> Config:
    try:
        return load_config(config_path, start=Path(repo))
    except Exception as exc:  # surface any config error plainly, don't traceback at the user
        err.print(f"[red]Config error:[/red] {exc}")
        raise typer.Exit(code=2) from exc


def _gather(to_ref: str, from_ref: str | None, repo: str, config: Config, *, no_github: bool):
    try:
        items, warnings = collect(
            to_ref,
            from_ref,
            repo_path=repo,
            use_github=not no_github,
            slug=config.github_repo or None,
        )
    except CollectError as exc:
        err.print(f"[red]Collection failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    for warning in warnings:
        err.print(f"[yellow]warning:[/yellow] {warning}")
    publishable, dropped = classify_all(items, config)
    return publishable, dropped


# ---------------------------------------------------------------------------


@app.command()
def init(
    path: Path = typer.Option(Path(".changelog.yml"), "--path", help="Where to write the config."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing file."),
) -> None:
    """Write a starter .changelog.yml."""
    if path.exists() and not force:
        err.print(f"[yellow]{path} already exists.[/yellow] Use --force to overwrite.")
        raise typer.Exit(code=1)
    path.write_text(EXAMPLE_CONFIG, encoding="utf-8")
    console.print(f"[green]Wrote[/green] {path}")


@app.command("collect")
def collect_cmd(
    to_ref: str = typer.Option(..., "--to", help="Newer ref (tag, branch or sha)."),
    from_ref: str | None = typer.Option(None, "--from", help="Older ref. Defaults to previous tag."),
    repo: str = typer.Option(".", "--repo", help="Path to the git checkout."),
    config_path: Path | None = typer.Option(None, "--config", help="Path to .changelog.yml."),
    no_github: bool = typer.Option(False, "--no-github", help="Skip the GitHub PR lookup."),
    as_json: bool = typer.Option(False, "--json", help="Print raw JSON instead of a table."),
) -> None:
    """Show what changed between two refs. Run this FIRST on a real repo."""
    config = _load(config_path, repo)
    publishable, dropped = _gather(to_ref, from_ref, repo, config, no_github=no_github)

    if as_json:
        console.print_json(
            json.dumps(
                {
                    "publishable": [item.model_dump(mode="json") for item in publishable],
                    "dropped": [item.model_dump(mode="json") for item in dropped],
                }
            )
        )
        return

    table = Table(title=f"{from_ref or previous_tag(to_ref, repo) or 'start'} → {to_ref}")
    table.add_column("id", style="cyan", no_wrap=True)
    table.add_column("src")
    table.add_column("kind", style="magenta")
    table.add_column("title")
    for item in publishable:
        table.add_row(item.id, item.source, item.kind.value, item.title)
    console.print(table)
    console.print(
        f"[green]{len(publishable)}[/green] publishable, "
        f"[dim]{len(dropped)} filtered out (internal/ignored)[/dim]"
    )


@app.command()
def preview(
    to_ref: str = typer.Option(..., "--to", help="Newer ref (also used as the version string)."),
    from_ref: str | None = typer.Option(None, "--from", help="Older ref. Defaults to previous tag."),
    repo: str = typer.Option(".", "--repo", help="Path to the git checkout."),
    config_path: Path | None = typer.Option(None, "--config", help="Path to .changelog.yml."),
    no_github: bool = typer.Option(False, "--no-github", help="Skip the GitHub PR lookup."),
    show_prompt: bool = typer.Option(
        False, "--show-prompt", help="Print the exact prompt we would send, and stop."
    ),
) -> None:
    """Rule-based changelog — no API key, no cost, no network beyond GitHub.

    Also the fastest way to see the prompt: `--show-prompt`.
    """
    config = _load(config_path, repo)
    publishable, _ = _gather(to_ref, from_ref, repo, config, no_github=no_github)

    if show_prompt:
        system = build_system_prompt(config)
        user = build_user_prompt(publishable, config, to_ref)
        console.rule("system prompt")
        console.print(system, highlight=False, markup=False)
        console.rule("user prompt")
        console.print(user, highlight=False, markup=False)
        console.rule()
        # Haiku 4.5 pricing: $1 / $5 per million tokens in / out.
        cost = estimate_cost(system, user, input_per_mtok=1.0, output_per_mtok=5.0)
        console.print(f"[dim]rough estimated cost for this release: ${cost:.4f}[/dim]")
        return

    response = rule_based_response(publishable, to_ref, config)
    console.print(render_markdown(response), highlight=False, markup=False)


@app.command()
def generate(
    to_ref: str = typer.Option(..., "--to", help="Newer ref (also used as the version string)."),
    from_ref: str | None = typer.Option(None, "--from", help="Older ref. Defaults to previous tag."),
    repo: str = typer.Option(".", "--repo", help="Path to the git checkout."),
    config_path: Path | None = typer.Option(None, "--config", help="Path to .changelog.yml."),
    no_github: bool = typer.Option(False, "--no-github", help="Skip the GitHub PR lookup."),
    style: str | None = typer.Option(
        None, "--style", help=f"Override the configured tone: {' | '.join(TONES)}."
    ),
    fmt: OutputFormat = typer.Option(OutputFormat.markdown, "--format", help="Render target."),
    out: Path | None = typer.Option(None, "--out", help="Write to this file instead of stdout."),
    update_changelog: Path | None = typer.Option(
        None, "--update-changelog", help="Insert the section into this CHANGELOG.md (idempotent)."
    ),
) -> None:
    """Full pipeline: collect → classify → LLM rewrite → render."""
    from .llm import generate_notes  # imported here so `preview` works before it's built

    config = _load(config_path, repo)
    if style:
        # `model_copy` does NOT re-run validation, so an unchecked value here
        # would sail straight into the prompt as `Tone: shakespearean.` This
        # check is what actually enforces the Literal on Config.tone.
        if style not in TONES:
            err.print(f"[red]Unknown --style '{style}'.[/red] Choose one of: {', '.join(TONES)}")
            raise typer.Exit(code=2)
        config = config.model_copy(update={"tone": style})
    publishable, _ = _gather(to_ref, from_ref, repo, config, no_github=no_github)

    try:
        response, warnings = generate_notes(publishable, config, to_ref)
    except NotImplementedError as exc:
        err.print(f"[yellow]Not built yet:[/yellow] {exc}")
        raise typer.Exit(code=3) from exc

    for warning in warnings:
        err.print(f"[yellow]warning:[/yellow] {warning}")

    if fmt is OutputFormat.json:
        rendered = json.dumps(response.model_dump(mode="json"), indent=2)
    elif fmt is OutputFormat.release:
        rendered = render_github_release(response)
    else:
        rendered = render_markdown(response)

    if update_changelog:
        changed = update_changelog_file(update_changelog, render_markdown(response), to_ref)
        console.print(
            f"[green]Updated[/green] {update_changelog}"
            if changed
            else f"[dim]{update_changelog} already contains {to_ref}; nothing to do.[/dim]"
        )

    if out:
        out.write_text(rendered, encoding="utf-8")
        console.print(f"[green]Wrote[/green] {out}")
    elif not update_changelog:
        console.print(rendered, highlight=False, markup=False)
