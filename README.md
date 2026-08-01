# ChangeLogScriptGenerator

AI-powered changelog & release notes generator: turns Git commits and merged PRs
between two tags into polished, customer-facing release notes via an LLM pipeline.

**Status:** Phase 1 — CLI runs end-to-end with rule-based output; the LLM step is next.

👉 **Start here: [PROGRESS.md](PROGRESS.md)** — what's built, why it's shaped that way, and what to do next.

## Why

Writing release notes is toil. Raw commit messages are written for engineers, not
customers. This tool collects commits/PRs between two refs, classifies them
(Features / Improvements / Fixes / Breaking), and uses an LLM with a schema-enforced
JSON contract to rewrite them into publishable prose — always reviewed by a human
via PR before publishing.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

changelog-gen init                                  # write a .changelog.yml
changelog-gen collect --to v1.4.0                   # what changed? (a table)
changelog-gen preview --to v1.4.0                   # changelog, rules only — no API key
changelog-gen preview --to v1.4.0 --show-prompt     # the exact prompt + cost estimate
changelog-gen generate --to v1.4.0                  # full LLM pipeline (needs ANTHROPIC_API_KEY)

pytest -q
```

`--from` defaults to the previous tag. Add `--no-github` to skip the PR lookup.

## Design in one diagram

```
   git log ─┐
            ├─► collect ──► classify ──► [ LLM rewrite ] ──► render ──► Markdown / PR
GitHub PRs ─┘   (facts)     (buckets)     ↑ the only         (templates)
                                            unpredictable step
```

**Deterministic shell, probabilistic core.** Everything around the model call is
plain, testable Python. The LLM does exactly one job — rewrite grouped facts into
customer-facing prose — and returns JSON that is schema-validated, retried once on
failure, and falls back to a rule-based render so a release never blocks.

Every generated sentence must cite the `source_ids` it came from; entries citing
unknown ids are rejected. That's the anti-hallucination guard.

## Docs & tracking

| Doc | Purpose |
|---|---|
| [PROGRESS.md](PROGRESS.md) | Status dashboard, mental model, your next session |
| [TODO.md](TODO.md) | Granular checklist per phase, with skills and done-criteria |
| [docs/LEARNING.md](docs/LEARNING.md) | The AI concepts, explained — mapped to files in this repo |
| [docs/BRD.pdf](docs/BRD.pdf) | Business requirements, personas, scope, monetization, kill criteria |
| [docs/Technical-Design.pdf](docs/Technical-Design.pdf) | Architecture, diagrams, exact build steps |
| [docs/Build-Phases-and-Learning-Roadmap.pdf](docs/Build-Phases-and-Learning-Roadmap.pdf) | Phase plan + LLM/agentic learning roadmap |
| [diagrams/](diagrams/) | Mermaid sources (.mmd) + rendered PNGs |

## Layout

```
src/changelog_gen/
  cli.py        # Typer entrypoint: init / collect / preview / generate
  collect.py    # git + GitHub API collector, commit↔PR de-duplication
  models.py     # Pydantic: ChangeItem, LLMResponse, hallucination guard
  config.py     # .changelog.yml loading
  classify.py   # rules-first bucketing (no AI)
  llm.py        # prompt building, validation, retry loop, fallback
  prompts/      # versioned Jinja2 prompt templates (system + user)
  templates/    # Markdown / GitHub Release render templates
  render.py     # renderers + rule-based fallback response
tests/          # 60 passing, 4 skipped (the LLM loop — see TODO.md #2)
```

## Roadmap

- **Phase 1 (Aug 3–16):** CLI MVP — `changelog-gen generate --from v1.3.0 --to v1.4.0`
- **Phase 2 (Aug 17–30):** GitHub Action — changelog PR on tag push
- **Phase 3 (Aug 31–Sep 13):** Public launch + validation (kill gate: 20 signups / 10 repos)
- **Phase 4+:** Hosted Pro (dashboard, changelog pages, Stripe)

## Privacy

Only commit/PR metadata leaves your machine — titles, bodies, labels. **Never
source diffs.** API keys come from environment variables only and are never logged.
