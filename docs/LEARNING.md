# LEARNING — the AI concepts in this project, explained plainly

The point of this project is not the changelog tool. It's that by the end you
can say *"I've shipped a production LLM pipeline"* and back it with a repo.

Each concept below has three parts: **what it is** (no jargon), **where it
lives in this repo** (so it's concrete, not abstract), and **prove it**
(a small thing to do that shows you actually get it).

Work through them in order. They're sequenced so each one unlocks the next.

---

## Stage 1 — LLM engineering fundamentals

### 1.1 Pipeline vs. agent — and why this is a pipeline

**What it is.** An *agent* decides its own next step in a loop: plan → act →
observe → repeat. A *pipeline* has the steps fixed in advance by you.

Agents are exciting and mostly the wrong tool. They're slower, more expensive,
harder to debug, and fail in ways you can't reproduce. The rule of thumb:
**if you can write the steps down, write the steps down.** Reach for an agent
only when the path genuinely can't be known ahead of time.

For this tool the steps are always the same — collect, classify, rewrite,
render — so it's a pipeline with exactly one model call in the middle.

**Where it lives.** The whole package. The model is called from exactly one
function: `generate_notes` in [../src/changelog_gen/llm.py](../src/changelog_gen/llm.py).
Everything else is ordinary Python.

**Prove it.** Read Anthropic's *Building Effective Agents* essay, then answer:
name one change to this product that would genuinely justify an agent loop.
(Hint: think about what happens when a PR body says "see the linked design doc".)

---

### 1.2 System prompt vs. user prompt

**What it is.** The **system prompt** is the model's job description: who it is,
what rules it must never break. It's the same on every call. The **user prompt**
is this specific request's data.

Splitting them isn't cosmetic. The system prompt is *stable*, which means it can
be cached later (you pay ~10% for cached tokens). Bury your rules inside the
per-release text and you've thrown that away.

**Where it lives.** [../src/changelog_gen/prompts/system.j2](../src/changelog_gen/prompts/system.j2)
(role + 7 hard rules) and [../src/changelog_gen/prompts/release.j2](../src/changelog_gen/prompts/release.j2)
(product, changes, few-shot examples, schema).

They're **Jinja templates in version control**, not f-strings, so a prompt change
shows up in `git diff` and gets reviewed like code. Prompts are code.

**Prove it.**
```bash
changelog-gen preview --to HEAD --show-prompt
```
Change `tone: friendly` to `tone: technical` in `.changelog.yml` and run it
again. Watch what moves.

---

### 1.3 Few-shot examples

**What it is.** Showing beats telling. Two worked examples of *bad commit → good
entry* teach the model the transformation far more reliably than three paragraphs
describing it.

**Where it lives.** The two `Example —` blocks in `release.j2`. Note the second
one demonstrates *merging* two commits into one sentence — a behaviour that's
almost impossible to elicit with prose instructions alone.

**Prove it.** Delete the examples, run `generate` on a real repo, compare. Put
them back. This is a 5-minute experiment that will change how you write prompts.

---

### 1.4 Structured outputs — the big one

**What it is.** By default a model returns free text, and "please return JSON"
is a *request*, not a *guarantee*. Sometimes you get ` ```json ` fences.
Sometimes a friendly "Here are your release notes!" preamble. Sometimes a field
name that's subtly wrong.

Structured outputs flip that: you hand the API a JSON Schema and it constrains
generation so the output *must* match. Same idea as a type system — push errors
to the boundary instead of three functions downstream.

**Where it lives.**
- The schema is **generated from the Pydantic model**, not hand-written:
  `response_json_schema()` in [../src/changelog_gen/models.py](../src/changelog_gen/models.py).
  One source of truth, so the prompt and the validator can never drift.
- `LLMResponse` sets `extra="forbid"`. That's not fussiness — it becomes
  `additionalProperties: false` in the schema, which the API's structured-output
  support requires.
- `parse_and_validate` in `llm.py` is the belt-and-braces check that runs even
  when the API is enforcing the schema.

**Prove it.** TODO #3: implement it with `output_config={"format": {...}}` and
measure how often the retry path fires with it on vs. off. That number is your
first eval metric.

---

### 1.5 The reliability loop: validate → retry with feedback → fall back

**What it is.** Three layers, each catching what the previous one missed:

1. **Validate.** Never render what you haven't checked.
2. **Retry with feedback.** On failure, send the *validation error itself* back
   to the model. "headline: field required" is actionable; a bare retry is a
   coin flip. Once, not forever — if it fails twice, more attempts won't help.
3. **Fall back.** Two failures → render from rules instead. The output is
   rougher, but the release ships.

That third layer is the one people skip, and it's the one that makes this a
product rather than a demo. Your user is a CI job at 11pm on release night.
It must not go red because a model got creative.

**Where it lives.** `generate_notes` in `llm.py` (your build session), with the
fallback provided by `rule_based_response` in
[../src/changelog_gen/render.py](../src/changelog_gen/render.py) — note that it
returns *exactly the same type* as the model path, which is what makes the
fallback a drop-in.

**Prove it.** The four skipped tests in [../tests/test_llm.py](../tests/test_llm.py)
each test one layer. Make them pass.

---

### 1.6 Grounding, or: how to stop a model inventing features

**What it is.** A model asked to make commit messages sound appealing will
sometimes make them sound *more* appealing than the truth. In a changelog that's
not a quirk, it's a customer support ticket.

The fix here is **citation + verification**. Every generated sentence must list
the `source_ids` it came from. Then we check every cited id against the ids we
actually supplied. Cite `#999` when we never gave you `#999`? Rejected.

It's about twenty lines of code and it's the highest-leverage safety measure in
the project. Generalise the pattern: *make the model cite its sources, then
verify the citations mechanically.* That's most of RAG evaluation too.

**Where it lives.** `unknown_source_ids` in `models.py`; the
`test_parse_and_validate_rejects_hallucinated_source_ids` test.

Note the deliberate softness: `a1b2` is accepted for `a1b2c3`, because a
shortened sha is sloppy, not dishonest. Guards that are too strict get disabled.

**Prove it.** Ask: what's the equivalent guard for a customer-support bot? For a
document summariser?

---

### 1.7 Token economics

**What it is.** You pay per token, in and out, at different rates. Two habits
cover 90% of cost control:

- **Send less.** `ChangeItem.to_prompt_dict()` drops null fields and truncates
  bodies to 400 chars. Boring, and it's most of the saving.
- **Batch.** One call per *release*, not per change. Cheaper, and it's the only
  way the model can merge two related commits into one sentence.

Current math: Haiku 4.5 at $1/$5 per million tokens in/out. A 50-change release
is roughly 5K in + 1K output ≈ **$0.01**. Budget was $0.05. Comfortable.

**Where it lives.** `to_prompt_dict()` in `models.py`; `estimate_cost()` in
`llm.py` (deliberately crude — see below).

**Prove it.** Replace the crude 4-chars-per-token estimate with the API's real
`count_tokens` endpoint. **Never use `tiktoken`** — that's OpenAI's tokenizer and
it under-counts Claude tokens by 15–20%, more on code.

---

### 1.8 Evals

**What it is.** "Did my prompt change make it better?" is unanswerable by
eyeballing one output. An eval is a fixed set of inputs plus a checklist of
qualities the output must have, so the question becomes a number.

For this project the checklist is: no invented features · correct bucketing ·
cites real sources · one sentence per entry · no internal jargon.

**Where it lives.** Not yet — that's Phase 1 evening 5 (`docs/eval-cases.md`).
But the raw material is already accumulating: **every ugly commit message you
add to `tests/test_classify.py` is an eval case.** Collect them from day one;
it's free now and a whole project later.

**Prove it.** Build the 10-case file. Then in Phase 2, automate the grading with
a second model call (LLM-as-judge) and look at `promptfoo` for tooling.

---

## Stage 2 — Agentic patterns (Sep–Oct, alongside Phases 3–4)

Not yet — listed so you know where this is going.

- **Tool use / function calling.** Let the model call `fetch_pr_details` when a
  title is too vague, instead of pre-feeding it everything. Upgrade the
  classifier's leftovers path first — it's the smallest useful version.
- **Agent loops.** When they beat pipelines (rarely) and how to bound them.
- **MCP.** Build a tiny MCP server exposing `generate_changelog` as a tool →
  instantly usable from Claude Desktop/Code. One evening, great demo, and a
  marketable skill on its own.
- **Claude Agent SDK.** Build the Phase-4 "draft announcement → await approval →
  publish" flow as a small stateful agent.

## Stage 3 — Productising AI (Oct+)

- **RAG basics** — "ask your changelog" search on hosted pages.
- **Ops for AI products** — logging every LLM call, cost dashboards, versioned
  prompts as deploys.
- **Packaging AI as a service** — fixed-scope automations for small businesses.
  This repo is the portfolio proof.

---

## Self-check: can you answer these without looking?

If you can answer all eight, you understand this project.

1. Why is the LLM call *one per release* instead of one per change?
2. What happens if the model returns valid JSON that cites a commit that doesn't exist?
3. What happens if the model returns invalid JSON twice in a row?
4. Why does `LLMResponse` set `extra="forbid"`?
5. Why keep the system prompt separate from the user prompt?
6. Why does the tool prefer a PR over the commit that squash-merged it?
7. Why is the classifier rules-first instead of asking the model?
8. What's the fallback's most important property? *(Hint: its type.)*

---

## Learning log

One line per session. Future-you will want this when writing the launch posts —
and "how I keep my LLM under $0.05 a release" is a post that writes itself if
you've been logging the numbers.

| Date | Session | What I learned / what surprised me |
|---|---|---|
| 2026-08-01 | Phase 0 + Phase 1 evenings 1–3 scaffolded | Pipeline shape is the whole design: one probabilistic step, deterministic everywhere else. The rule-based renderer is both the safety net *and* the way to verify the collector without spending a cent. |
| | | |
