"""Tests for the prompt/validation layer — and your spec for build session 4.

Everything above the `YOUR TASK` divider passes today.
Everything below it is SKIPPED. Removing those skip markers and making the
tests pass IS the next build session. Read them first: they are a precise,
executable description of the reliability loop you're about to write.
"""

from __future__ import annotations

import json

import pytest

from changelog_gen.config import Config
from changelog_gen.llm import (
    SchemaViolation,
    StubProvider,
    build_system_prompt,
    build_user_prompt,
    parse_and_validate,
)
from changelog_gen.models import ChangeItem, Kind

ITEMS = [
    ChangeItem(id="#482", source="pr", title="Add webhook retries", kind=Kind.FEATURE),
    ChangeItem(id="a1b2c3", source="commit", title="Handle 429 from the API", kind=Kind.FIX),
]
KNOWN_IDS = [item.id for item in ITEMS]

VALID_JSON = json.dumps(
    {
        "version": "v1.4.0",
        "headline": "Webhooks are now reliable.",
        "sections": [
            {
                "name": "Features",
                "entries": [
                    {"text": "Webhooks retry automatically.", "source_ids": ["#482"]}
                ],
            },
            {
                "name": "Bug Fixes",
                "entries": [{"text": "Rate limits are handled gracefully.", "source_ids": ["a1b2c3"]}],
            },
        ],
    }
)


# ---------------------------------------------------------------------------
# Prompt building — passing
# ---------------------------------------------------------------------------


def test_system_prompt_carries_tone_and_audience():
    prompt = build_system_prompt(Config(tone="friendly", audience="customers"))
    assert "friendly" in prompt
    assert "customers" in prompt
    assert "Never invent a feature" in prompt


def test_user_prompt_contains_changes_schema_and_product():
    config = Config(product="Acme API")
    prompt = build_user_prompt(ITEMS, config, "v1.4.0")

    assert "Acme API" in prompt
    assert "v1.4.0" in prompt
    assert "#482" in prompt and "a1b2c3" in prompt
    assert "source_ids" in prompt  # the schema made it in
    assert "Your previous response was rejected" not in prompt


def test_user_prompt_appends_the_validation_error_on_retry():
    """Retry-with-feedback: the model is told exactly what it got wrong."""
    prompt = build_user_prompt(ITEMS, Config(), "v1.4.0", retry_error="headline: field required")
    assert "Your previous response was rejected" in prompt
    assert "headline: field required" in prompt


def test_prompt_omits_empty_bodies_to_save_tokens():
    prompt = build_user_prompt(ITEMS, Config(), "v1.4.0")
    assert '"body"' not in prompt  # none of ITEMS has a body


# ---------------------------------------------------------------------------
# Validation — passing
# ---------------------------------------------------------------------------


def test_parse_and_validate_accepts_good_json():
    response = parse_and_validate(VALID_JSON, KNOWN_IDS)
    assert response.version == "v1.4.0"
    assert len(response.sections) == 2


def test_parse_and_validate_strips_markdown_fences():
    """Models love wrapping JSON in ```json fences. Handle it, don't fight it."""
    fenced = f"```json\n{VALID_JSON}\n```"
    assert parse_and_validate(fenced, KNOWN_IDS).version == "v1.4.0"


def test_parse_and_validate_rejects_non_json():
    with pytest.raises(SchemaViolation, match="not valid JSON"):
        parse_and_validate("Here are your release notes!", KNOWN_IDS)


def test_parse_and_validate_rejects_missing_fields():
    with pytest.raises(SchemaViolation, match="did not match the schema"):
        parse_and_validate(json.dumps({"version": "v1.4.0", "sections": []}), KNOWN_IDS)


def test_parse_and_validate_rejects_extra_fields():
    payload = json.loads(VALID_JSON)
    payload["confidence"] = 0.9
    with pytest.raises(SchemaViolation, match="did not match the schema"):
        parse_and_validate(json.dumps(payload), KNOWN_IDS)


def test_parse_and_validate_rejects_hallucinated_source_ids():
    """The anti-hallucination guard: a cited id we never supplied means it was invented."""
    payload = json.loads(VALID_JSON)
    payload["sections"][0]["entries"][0]["source_ids"] = ["#999"]

    with pytest.raises(SchemaViolation, match="#999"):
        parse_and_validate(json.dumps(payload), KNOWN_IDS)


def test_parse_and_validate_tolerates_sha_prefixes():
    """Models often shorten a sha. `a1b2` for `a1b2c3` is not a hallucination."""
    payload = json.loads(VALID_JSON)
    payload["sections"][1]["entries"][0]["source_ids"] = ["a1b2"]
    assert parse_and_validate(json.dumps(payload), KNOWN_IDS)


# ===========================================================================
# >>> YOUR TASK — build session 4 <<<
# Delete the `skip` marker on each test below, then implement
# `generate_notes` in src/changelog_gen/llm.py until they all pass.
# ===========================================================================

pytestmark_reason = "Build session 4: implement generate_notes() in llm.py, then remove this skip."


@pytest.mark.skip(reason=pytestmark_reason)
def test_generate_notes_happy_path():
    from changelog_gen.llm import generate_notes

    provider = StubProvider([VALID_JSON])
    response, warnings = generate_notes(ITEMS, Config(), "v1.4.0", provider=provider)

    assert response.headline == "Webhooks are now reliable."
    assert warnings == []
    assert len(provider.calls) == 1


@pytest.mark.skip(reason=pytestmark_reason)
def test_generate_notes_retries_once_with_the_error_fed_back():
    from changelog_gen.llm import generate_notes

    provider = StubProvider(["not json at all", VALID_JSON])
    response, warnings = generate_notes(ITEMS, Config(), "v1.4.0", provider=provider)

    assert response.headline == "Webhooks are now reliable."
    assert len(provider.calls) == 2
    assert warnings, "a retry should be surfaced to the user as a warning"

    # The second prompt must contain the validation error from the first attempt.
    _system, second_user_prompt = provider.calls[1]
    assert "Your previous response was rejected" in second_user_prompt


@pytest.mark.skip(reason=pytestmark_reason)
def test_generate_notes_falls_back_to_rule_based_after_two_failures():
    """A release must never be blocked by a misbehaving model."""
    from changelog_gen.llm import generate_notes

    provider = StubProvider(["garbage", "still garbage"])
    response, warnings = generate_notes(ITEMS, Config(), "v1.4.0", provider=provider)

    assert response.version == "v1.4.0"
    assert response.sections, "the fallback must still produce usable notes"
    assert any("fallback" in w.lower() or "rule-based" in w.lower() for w in warnings)


@pytest.mark.skip(reason=pytestmark_reason)
def test_generate_notes_does_not_retry_transport_errors():
    """Retrying a 401 just burns time. Only schema failures are worth a second try."""
    from changelog_gen.llm import LLMError, generate_notes

    class Failing:
        calls = 0

        def complete(self, system: str, user: str) -> str:
            Failing.calls += 1
            raise LLMError("401 unauthorized")

    response, warnings = generate_notes(ITEMS, Config(), "v1.4.0", provider=Failing())

    assert Failing.calls == 1
    assert response.sections  # fell back rather than raising
    assert warnings
