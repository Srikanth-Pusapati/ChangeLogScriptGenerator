# TODO

Checkboxes render on GitHub — tick them as you go. Every task has a
**Learn** line (what skill it buys you) and a **Done when** line (so "done"
isn't a feeling). Narrative status lives in [PROGRESS.md](PROGRESS.md).

---

## Phase 0 — Setup ✅ complete

- [x] GitHub repo + design docs pushed
- [x] Python package skeleton (`pyproject.toml`, `src/changelog_gen/`)
- [x] Virtualenv + editable install, `changelog-gen --help` runs
- [x] Test suite wired (`pytest -q`)

- [ ] **#0 (optional, 5 min) — switch to `uv`**
  `brew install uv` → `uv venv` → `uv pip install -e ".[dev]"`. Everything else
  is unchanged; `pyproject.toml` is already standard PEP-621.
  **Learn:** modern Python packaging; `uv` is 10–100× faster than pip and is
  what the design doc assumes.
  **Done when:** `uv run changelog-gen --help` works.

---

## Phase 1 — CLI MVP (Aug 3–16)

### ✅ Evening 1 — Bootstrap
- [x] Package layout, Typer entrypoint, deps, first commit

### ✅ Evening 2 — Collector
- [x] `git log` parsing with unit separators (survives multi-line bodies)
- [x] Auto-detect previous tag via `git describe`
- [x] GitHub merged-PR fetch with pagination + date windowing
- [x] Commit↔PR de-duplication (squash-merge `(#482)` detection)
- [x] `changelog-gen collect --to <ref> --json` to eyeball raw output
- [x] Graceful degradation: no token / no network / no remote → commits only

### ✅ Evening 3 — Normalise + classify
- [x] Conventional Commit parsing (`feat(scope)!: subject`)
- [x] Prefix→kind and label→kind maps, `label_map` config override
- [x] Breaking detection (`!`, `BREAKING CHANGE:`, configured labels)
- [x] Ignore globs; internal changes dropped
- [x] Test corpus of 13 messy real-world messages

### ⬜ Evening 4 — **The LLM call** ← YOU ARE HERE

- [ ] **#1 — `AnthropicProvider.complete`**
  Roadmap is in the docstring in [src/changelog_gen/llm.py](src/changelog_gen/llm.py).
  **Learn:** the Messages API shape; why `response.content` is a *list of blocks*,
  not a string (indexing `content[0].text` blindly is the classic first bug).
  **Done when:** a scratch script gets real text back from Claude.

- [ ] **#2 — `generate_notes` reliability loop**
  build prompt → call → validate → retry ONCE with the error → fall back to rules.
  **Learn:** retry-with-feedback, and why a production pipeline must degrade
  instead of raising. A release must never be blocked by a stray markdown fence.
  **Done when:** the 4 skipped tests in [tests/test_llm.py](tests/test_llm.py) pass with the skip markers removed.

- [ ] **#3 — Upgrade to real structured outputs**
  Swap hand-parsing for `output_config={"format": {"type": "json_schema", ...}}`
  so the API enforces the schema instead of us hoping. (`LLMResponse` already
  sets `extra="forbid"`, which the API requires — that wasn't an accident.)
  **Learn:** schema-constrained generation — the single skill your roadmap calls
  out as separating demo-builders from production-builders.
  **Done when:** the retry path stops firing on well-formed inputs.

- [ ] **#4 — Measure it**
  Record how often the retry fires with structured outputs ON vs OFF, and the
  real token cost of one release (use the API's `count_tokens` — never `tiktoken`,
  it's calibrated for a different model family).
  **Learn:** token economics; your first real eval metric.
  **Done when:** you can state cost-per-release and retry-rate as numbers.

### ⬜ Evening 5 — Ship it and look at real output
- [ ] Run on **3 real repos** (yours + 2 friends'). Save the output.
- [ ] Every ugly commit message you hit → add to `tests/test_classify.py`
  **Learn:** building an eval set from production data, which is how real LLM
  products get better. Start on day one and it's free; start in month three and
  it's a project.
- [ ] Tune `prompts/system.j2` against that real output — one change at a time
- [ ] `--update-changelog CHANGELOG.md` end-to-end on this repo
- [ ] Write `docs/eval-cases.md`: 10 input→expected-qualities cases
  (no hallucinated features / correct bucketing / cites sources)

**Phase 1 exit criteria:** a publishable changelog from a real repo in under 2 minutes.

---

## Phase 2 — GitHub Action + polish (Aug 17–30)

- [ ] `action.yml` composite action: checkout `fetch-depth: 0` → setup-python →
      `pip install changelog-gen` → `generate` → `peter-evans/create-pull-request`
- [ ] Trigger on `push: tags: ['v*']`; secret `ANTHROPIC_API_KEY` (`GITHUB_TOKEN` is built in)
- [ ] Human-in-the-loop by default — it opens a PR, never a silent commit
- [ ] README with a GIF demo + sample outputs
- [ ] Publish to PyPI (`pipx install changelog-gen`)
- [ ] Golden tests: 3 frozen releases with recorded LLM responses, so refactors
      can't silently change output
- [ ] Automate the eval file with an LLM-as-judge grader
  **Learn:** LLM evals — the skill that makes prompt changes measurable instead of vibes

**Exit criteria:** 5 people ran it, 5 honest complaints collected.

---

## Phase 3 — Launch + validation (Aug 31–Sep 13)

- [ ] Landing page with email capture
- [ ] Show HN + r/webdev + 2 dev Discords
- [ ] GitHub Marketplace listing
- [ ] Interview every active user

**🚦 Kill gate:** ≥20 signups OR ≥10 active repos. Otherwise archive with a
written retro and move to the Webhook Observability Dashboard. **Do not extend
the deadline.**

---

## Phase 4+ — only if the gate passes

- [ ] GitHub App, dashboard, hosted changelog pages, Stripe ($15/$29)
- [ ] Tool use: let the model call `fetch_pr_details` instead of pre-feeding everything
- [ ] MCP server exposing `generate_changelog` — usable from Claude Desktop/Code
- [ ] "Ask your changelog" search (RAG basics: embeddings, chunking, retrieval)

---

## Weekly rhythm (from the phase plan — the part people skip)

- [ ] 2 build sessions, 2–3 hrs each, **calendar-blocked**
- [ ] 1 **distribution** hour — show someone, post somewhere, answer a user
- [ ] 30 min learning ([docs/LEARNING.md](docs/LEARNING.md)), + one line in the log

> The distribution hour is the difference between a repo and a product.
