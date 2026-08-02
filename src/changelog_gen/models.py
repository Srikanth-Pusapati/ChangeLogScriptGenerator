"""The vocabulary the whole pipeline speaks.

ELI5
----
Two kinds of shapes live here:

1. `ChangeItem` — OUR shape. One row per commit or merged PR, after we've
   normalised it. Everything downstream (classifier, prompt, renderer) only
   ever sees `ChangeItem`s, so it doesn't care whether the fact came from
   `git log` or the GitHub API.

2. `LLMResponse` (+ `Section`, `Entry`) — THE CONTRACT with the model. We hand
   the model a JSON schema generated from this class and refuse to render
   anything that doesn't validate against it. That's what stops a bad model
   response from becoming a bad changelog.

Why Pydantic and not a plain dict? Because a dict will happily hold
`{"headlin": "..."}` and blow up three functions later. Pydantic fails at the
boundary, with a message naming the field.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Kind(str, Enum):
    """The bucket a change lands in. `INTERNAL` means 'never show a customer'."""

    FEATURE = "feature"
    IMPROVEMENT = "improvement"
    FIX = "fix"
    BREAKING = "breaking"
    INTERNAL = "internal"


class ChangeItem(BaseModel):
    """One normalised unit of engineering activity.

    `id` is the thing we cite in the final changelog: a PR number like "#482"
    or a short commit sha like "a1b2c3". The LLM must reference these ids, and
    we reject any it invents — see `unknown_source_ids` below.
    """

    id: str
    source: Literal["commit", "pr"]
    title: str
    body: str | None = None
    labels: list[str] = Field(default_factory=list)
    kind: Kind = Kind.IMPROVEMENT
    refs: list[str] = Field(default_factory=list)  # linked issues, e.g. ["#123"]
    author: str | None = None
    url: str | None = None

    def to_prompt_dict(self) -> dict:
        """Compact form for the LLM prompt.

        Token economics lesson: we send the model the *minimum* it needs to
        write one sentence. Dropping nulls and truncating bodies is most of the
        difference between a $0.01 release and a $0.20 one.
        """
        d: dict = {"id": self.id, "kind": self.kind.value, "title": self.title}
        if self.body:
            d["body"] = self.body[:400]
        if self.labels:
            d["labels"] = self.labels
        if self.refs:
            d["refs"] = self.refs
        return d


# ---------------------------------------------------------------------------
# The LLM contract. Everything below is what the model must produce.
# ---------------------------------------------------------------------------


class Entry(BaseModel):
    """One published bullet point, plus the raw changes it was derived from."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    entries: list[Entry]


class LLMResponse(BaseModel):
    """The full release-notes payload.

    `extra="forbid"` is deliberate: if the model invents a field we want to
    know at validation time, not silently drop it.
    """

    model_config = ConfigDict(extra="forbid")

    version: str
    headline: str
    sections: list[Section]

    def all_source_ids(self) -> list[str]:
        return [sid for section in self.sections for entry in section.entries for sid in entry.source_ids]


def response_json_schema() -> dict:
    """The JSON schema we paste into the prompt.

    Single source of truth: the schema is *generated* from the Pydantic model,
    so the prompt and the validator can never drift apart.
    """
    return LLMResponse.model_json_schema()


# ---------------------------------------------------------------------------
# Anti-hallucination guard
# ---------------------------------------------------------------------------

_ID_NORMALISE = re.compile(r"^[#a-zA-Z0-9_.-]+$")


def normalise_id(raw: str) -> str:
    """Make ids comparable: strip whitespace, lowercase shas, keep '#' on PRs."""
    s = raw.strip()
    if s.startswith("#"):
        return s
    return s.lower()


def unknown_source_ids(response: LLMResponse, known_ids: list[str]) -> list[str]:
    """Return every source_id the model cited that we never gave it.

    This is the cheapest, most effective hallucination check in the whole
    project: an entry that cites a change we don't have is an entry the model
    invented. We reject the response and retry rather than publish it.
    """
    known = {normalise_id(k) for k in known_ids}
    # A commit sha may be cited in a shorter/longer form than we stored it in.
    unknown: list[str] = []
    for sid in response.all_source_ids():
        n = normalise_id(sid)
        if n in known:
            continue
        # Allow sha prefixes/extensions (a1b2c3 vs a1b2c3d4).
        if any(k.startswith(n) or n.startswith(k) for k in known if not k.startswith("#")):
            continue
        unknown.append(sid)
    return unknown
