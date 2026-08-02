"""Load and validate `.changelog.yml`.

ELI5
----
A config file is how the same generic tool produces on-brand output for very
different products. Tone, audience and the product one-liner all get injected
into the prompt; `ignore` and `breaking_labels` feed the deterministic
classifier.

Everything has a default, so a repo with no `.changelog.yml` still works. That
is the "zero-config first run" non-functional requirement from the BRD.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_NAME = ".changelog.yml"


class LLMConfig(BaseModel):
    provider: Literal["anthropic"] = "anthropic"
    # Haiku 4.5 is the cheap tier ($1 / $5 per million tokens in/out) and it
    # supports schema-constrained structured outputs, which is all we need.
    # A typical release is ~5K in / ~1K out => well under $0.05.
    model: str = "claude-haiku-4-5"
    max_tokens: int = 4000
    # One retry on a schema-validation failure, then fall back to rule-based
    # rendering. See llm.py for why the pipeline must never hard-block a release.
    max_retries: int = 1


class Config(BaseModel):
    product: str = ""
    # Explicit "owner/repo" override, for when the `origin` remote can't be
    # auto-parsed (GitHub Enterprise on a custom domain, unusual SSH aliases).
    github_repo: str = ""
    tone: Literal["professional", "friendly", "technical"] = "professional"
    audience: Literal["customers", "developers", "internal"] = "customers"
    sections: list[str] = Field(
        default_factory=lambda: ["Features", "Improvements", "Bug Fixes", "Breaking Changes"]
    )
    ignore: list[str] = Field(
        default_factory=lambda: ["chore(*", "chore:*", "ci:*", "build:*", "test:*", "bump *", "Merge branch*"]
    )
    breaking_labels: list[str] = Field(
        default_factory=lambda: ["breaking", "breaking-change", "breaking change"]
    )
    # Map your repo's PR labels onto our kinds, e.g. {"enhancement": "improvement"}.
    label_map: dict[str, str] = Field(default_factory=dict)
    llm: LLMConfig = Field(default_factory=LLMConfig)


def find_config(start: Path | None = None) -> Path | None:
    """Walk up from `start` looking for a `.changelog.yml`."""
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / DEFAULT_CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path | None = None, *, start: Path | None = None) -> Config:
    """Load config from `path`, or auto-discover it, or return defaults."""
    resolved = path or find_config(start)
    if resolved is None:
        return Config()
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise TypeError(f"{resolved} must contain a YAML mapping at the top level")
    return Config.model_validate(raw)


EXAMPLE_CONFIG = """\
# .changelog.yml — everything here is optional; delete what you don't need.

product: "Acme API — payments infrastructure for indie SaaS"
tone: friendly            # professional | friendly | technical
audience: customers       # customers | developers | internal

sections: [Features, Improvements, Bug Fixes, Breaking Changes]

# Commits/PRs whose title matches any of these globs never reach the LLM.
ignore:
  - "chore(*"
  - "chore:*"
  - "ci:*"
  - "bump *"

breaking_labels: [breaking, breaking-change]

# Map your repo's PR labels onto our buckets.
label_map:
  enhancement: improvement
  bug: fix

llm:
  provider: anthropic
  model: claude-haiku-4-5   # cheap tier is plenty for rewriting one sentence
  max_tokens: 4000
  max_retries: 1
"""
