# ChangeLogScriptGenerator

AI-powered changelog & release notes generator: turns Git commits and merged PRs
between two tags into polished, customer-facing release notes via an LLM pipeline.

**Status:** Phase 0 — design docs complete, CLI MVP in progress.

## Why

Writing release notes is toil. Raw commit messages are written for engineers, not
customers. This tool collects commits/PRs between two refs, classifies them
(Features / Improvements / Fixes / Breaking), and uses an LLM with a schema-enforced
JSON contract to rewrite them into publishable prose — always reviewed by a human
via PR before publishing.

## Docs

| Doc | Purpose |
|---|---|
| [docs/BRD.docx](docs/BRD.docx) | Business requirements, personas, scope, monetization, kill criteria |
| [docs/Technical-Design.docx](docs/Technical-Design.docx) | Architecture, component/sequence/deployment diagrams, exact build steps |
| [docs/Build-Phases-and-Learning-Roadmap.docx](docs/Build-Phases-and-Learning-Roadmap.docx) | Phase plan + LLM/agentic learning roadmap |
| [diagrams/](diagrams/) | Mermaid sources (.mmd) + rendered PNGs |

## Planned layout (Phase 1)

```
src/changelog_gen/
  cli.py        # Typer entrypoint
  collect.py    # git + GitHub API collector
  models.py     # Pydantic: ChangeItem, LLMResponse
  classify.py   # rules-first bucketing
  llm.py        # provider interface, schema validation, retry
  prompts/      # versioned Jinja2 prompt templates
  render.py     # Markdown / GitHub Release renderers
```

## Roadmap

- **Phase 1 (Aug 3–16):** CLI MVP — `changelog-gen generate --from v1.3.0 --to v1.4.0`
- **Phase 2 (Aug 17–30):** GitHub Action — changelog PR on tag push
- **Phase 3 (Aug 31–Sep 13):** Public launch + validation (kill gate: 20 signups / 10 repos)
- **Phase 4+:** Hosted Pro (dashboard, changelog pages, Stripe)

See the Build Phases doc for the full plan.
