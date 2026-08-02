"""The one probabilistic step — and the machinery that makes it safe.

ELI5
----
Everything else in this package is code you can predict. This module is where
we ask a language model to do something we can't write rules for: turn
"fix null check in webhook retry" into "Webhooks now retry reliably".

Because the model can be wrong, we wrap it in a **reliability loop**:

    build prompt -> call model -> parse JSON -> validate schema
                                                     |
                            valid? -> render         |
                            invalid? -> retry ONCE with the error appended
                            still invalid? -> fall back to rule-based render

That loop is the difference between a demo and a product. A release must never
fail to ship because a model returned a stray markdown fence.

STATUS
------
`build_system_prompt`, `build_user_prompt` and `parse_and_validate` are DONE —
you can inspect the exact prompt today with `changelog-gen preview --show-prompt`.

`AnthropicProvider.complete` and `generate_notes` are YOUR next build session.
Each has a numbered roadmap in its docstring and a test in `tests/test_llm.py`
waiting for you (remove the `skip` marker and make it pass). See TODO.md #4.
"""

from __future__ import annotations

import json
from typing import Protocol

from jinja2 import Environment, PackageLoader
from pydantic import ValidationError

from .config import Config
from .models import ChangeItem, LLMResponse, response_json_schema, unknown_source_ids
from .render import (
    group_by_section,
    rule_based_response,  # noqa: F401  <- the fallback; generate_notes will use it
)


class LLMError(RuntimeError):
    """Raised when we could not get a usable response out of the provider."""


class SchemaViolation(LLMError):
    """The model replied, but the reply doesn't satisfy our contract."""


# ---------------------------------------------------------------------------
# Prompt building  (DONE)
# ---------------------------------------------------------------------------


def _env() -> Environment:
    return Environment(
        loader=PackageLoader("changelog_gen", "prompts"),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def build_system_prompt(config: Config) -> str:
    """Role + hard rules. Stable across every release for a given config.

    Keeping this stable matters beyond tidiness: identical prefixes are what
    make prompt caching possible later, when volume justifies it.
    """
    return _env().get_template("system.j2").render(tone=config.tone, audience=config.audience)


def build_user_prompt(
    items: list[ChangeItem],
    config: Config,
    version: str,
    *,
    retry_error: str | None = None,
) -> str:
    """The per-release half: product context, grouped changes, schema.

    One call per release, not per change. That is both cheaper and *better* —
    the model can only merge two related commits into one entry if it sees
    them together.
    """
    grouped = {
        name: [item.to_prompt_dict() for item in group]
        for name, group in group_by_section(items, config)
    }
    return _env().get_template("release.j2").render(
        product=config.product,
        version=version,
        section_names=[name for name, _ in group_by_section(items, config)] or config.sections,
        changes_json=json.dumps(grouped, indent=2),
        schema_json=json.dumps(response_json_schema(), indent=2),
        retry_error=retry_error,
    )


# ---------------------------------------------------------------------------
# Validation  (DONE)
# ---------------------------------------------------------------------------


def parse_and_validate(raw: str, known_ids: list[str]) -> LLMResponse:
    """Text -> validated LLMResponse, or raise SchemaViolation.

    Three gates, cheapest first:
      1. Is it JSON at all? (models sometimes wrap it in ```json fences)
      2. Does it match the Pydantic schema?
      3. Does every cited source_id actually exist? <- the hallucination guard

    The error message is written to be fed straight back to the model on
    retry, so it names the problem in terms the model can act on.
    """
    text = _strip_code_fence(raw).strip()
    if not text:
        raise SchemaViolation("Response was empty.")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaViolation(f"Response was not valid JSON: {exc}") from exc

    try:
        response = LLMResponse.model_validate(payload)
    except ValidationError as exc:
        raise SchemaViolation(f"JSON did not match the schema: {exc}") from exc

    unknown = unknown_source_ids(response, known_ids)
    if unknown:
        raise SchemaViolation(
            "These source_ids were cited but do not exist in the input: "
            + ", ".join(unknown)
            + ". Only cite ids that were given to you."
        )

    return response


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class Provider(Protocol):
    """Anything that can turn (system, user) into text.

    Keeping this a Protocol rather than a base class means the fake provider in
    tests is just a small object with a `complete` method — no inheritance, no
    mocking library, no network in the test suite.
    """

    def complete(self, system: str, user: str) -> str: ...


class StubProvider:
    """A deterministic fake used by tests and `--offline`."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise LLMError("StubProvider ran out of scripted responses")
        return self._responses.pop(0)


class AnthropicProvider:
    """Real Claude client.

    >>> YOUR TASK (build session 4a) <<<

    Implement `complete`. The roadmap:

      1. `import anthropic` at the top of this file (it's already a dependency)
         and build a client in `__init__`:
             self._client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY
      2. In `complete`, call:
             self._client.messages.create(
                 model=self.model,
                 max_tokens=self.max_tokens,
                 system=system,
                 messages=[{"role": "user", "content": user}],
             )
      3. The response `.content` is a LIST of blocks, not a string. Find the
         first block whose `.type == "text"` and return its `.text`.
         (Indexing `content[0].text` blindly is the #1 beginner bug here.)
      4. Wrap `anthropic.APIError` in `LLMError` so callers only have to catch
         one exception type.

    STRETCH GOAL, and the real lesson: replace steps 2-3 with *structured
    outputs*, so the API itself enforces our schema instead of us hoping:

        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema",
                                      "schema": response_json_schema()}},
        )

    Then measure: how often does the retry path fire with structured outputs
    on vs off? That number is your first eval, and it's the thing that
    separates people who demo LLM apps from people who ship them.

    Note: `LLMResponse` uses `extra="forbid"`, which the API's schema support
    requires (`additionalProperties: false`). That's not an accident.
    """

    def __init__(self, model: str, max_tokens: int = 4000) -> None:
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError(
            "AnthropicProvider.complete is your next build session — see the "
            "docstring in src/changelog_gen/llm.py and TODO.md #4."
        )


def build_provider(config: Config) -> Provider:
    if config.llm.provider == "anthropic":
        return AnthropicProvider(config.llm.model, config.llm.max_tokens)
    raise LLMError(f"Unknown provider: {config.llm.provider}")


# ---------------------------------------------------------------------------
# The reliability loop
# ---------------------------------------------------------------------------


def generate_notes(
    items: list[ChangeItem],
    config: Config,
    version: str,
    *,
    provider: Provider | None = None,
) -> tuple[LLMResponse, list[str]]:
    """Produce validated release notes. Returns `(response, warnings)`.

    >>> YOUR TASK (build session 4b) <<<

    Implement the loop. The roadmap:

      1. `provider = provider or build_provider(config)`.
      2. `known_ids = [item.id for item in items]` — the allow-list for the
         hallucination check.
      3. `system = build_system_prompt(config)`.
      4. Loop `for attempt in range(config.llm.max_retries + 1):`
           a. `user = build_user_prompt(items, config, version,
                                        retry_error=last_error)`
           b. `raw = provider.complete(system, user)`
           c. `return parse_and_validate(raw, known_ids), warnings`
           d. on `SchemaViolation as exc`: record `last_error = str(exc)`,
              append a warning, and loop again.
           e. on `LLMError` (network/auth): break out — retrying a 401 is
              pointless.
      5. After the loop, fall back:
           `warnings.append("LLM failed; using rule-based render.")`
           `return rule_based_response(items, version, config), warnings`

    The fallback is not optional. Re-read the "never block a release" note at
    the top of this file before you're tempted to `raise` instead.
    """
    raise NotImplementedError(
        "generate_notes is your next build session — see the docstring in "
        "src/changelog_gen/llm.py and TODO.md #4. "
        "In the meantime, `changelog-gen preview` gives you a rule-based "
        "changelog with no API key required."
    )


def estimate_cost(system: str, user: str, *, input_per_mtok: float, output_per_mtok: float,
                  assumed_output_tokens: int = 1000) -> float:
    """Very rough $ estimate, using ~4 characters per token.

    Deliberately crude. When you need a real number, use the API's
    `count_tokens` endpoint — never a third-party tokenizer, which is
    calibrated for a different model family and will be wrong.
    """
    input_tokens = (len(system) + len(user)) / 4
    return (input_tokens / 1_000_000) * input_per_mtok + (
        assumed_output_tokens / 1_000_000
    ) * output_per_mtok
