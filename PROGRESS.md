# PROGRESS — where this project is, in plain English

> **Read this file first, every time you sit down.**
> It answers three questions: what exists, why it's shaped that way, and what you do next.
> Granular checkboxes live in [TODO.md](TODO.md). Concepts live in [docs/LEARNING.md](docs/LEARNING.md).

**Last updated:** 2026-08-01 · **Phase:** 0 done → Phase 1 in progress (3 of 5 evenings complete)

---

## 1. Where you are right now

You have a **working tool**. Not a finished one — a working one.

Today, on any git repo on your machine, you can run one command and get a
readable changelog out. It doesn't use AI yet: it uses rules. That's on
purpose. The rules-based version is both your *verification harness* (does the
collector actually find the right commits?) and your *safety net* (what the
tool falls back to when the AI misbehaves).

The AI step — the interesting 10% — is scaffolded, documented, and has failing
tests waiting for you. **That is your next build session, and it's deliberately
left for you to write.** Everything around it is done so that when you write
it, you're learning structured outputs and reliability loops, not fighting
`git log` parsing.

---

## 2. Try it in 60 seconds

```bash
cd ~/PersonalProjects/ChangeLogScriptGenerator
source .venv/bin/activate

changelog-gen --help
changelog-gen collect --to HEAD --no-github     # what changed? (a table)
changelog-gen preview --to HEAD --no-github     # the changelog, rules-only
changelog-gen preview --to HEAD --show-prompt   # the exact prompt + cost estimate
pytest -q                                        # 78 passing, 4 skipped
```

Point it at a repo with real tags to see it properly:

```bash
changelog-gen preview --repo ~/some/other/repo --from v1.2.0 --to v1.3.0
```

---

## 3. The mental model (this is the important part)

The whole design comes from one sentence: **deterministic shell, probabilistic core.**

```
   git log ─┐
            ├─► collect ──► classify ──► [ LLM rewrite ] ──► render ──► Markdown / PR
GitHub PRs ─┘   (facts)     (buckets)     ↑ the only         (templates)
                                            unpredictable
                                            step
```

Everything except the middle box is ordinary Python you can unit-test. The LLM
gets exactly **one job**: rewrite grouped facts into customer-facing prose, and
return JSON we validate against a schema before we trust a word of it.

Why this matters: most people building with LLMs put the model in charge of
everything and then can't debug it. Here, if the output is wrong you know
*which box* is wrong. That's the whole trick.

### What each file does — one line each

| File | Its one job |
|---|---|
| [models.py](src/changelog_gen/models.py) | The shapes. `ChangeItem` = our internal fact. `LLMResponse` = the contract the model must satisfy. |
| [config.py](src/changelog_gen/config.py) | Loads `.changelog.yml`. Tone/audience feed the prompt; ignore-globs feed the classifier. |
| [collect.py](src/changelog_gen/collect.py) | Finds what changed. `git log` for commits, GitHub API for PRs, then de-duplicates them. |
| [classify.py](src/changelog_gen/classify.py) | Buckets each change (Feature/Fix/…) using prefixes and labels. **No AI.** |
| [llm.py](src/changelog_gen/llm.py) | Builds the prompt, calls the model, validates, retries, falls back. ← your next session |
| [render.py](src/changelog_gen/render.py) | Jinja templates → Markdown. Also builds the no-AI fallback response. |
| [cli.py](src/changelog_gen/cli.py) | Thin wrapper. Parses flags, calls the above, prints. |

### Three design decisions worth understanding

**1. Why de-duplicate commits against PRs?**
A squash-merge leaves you with *both* a commit called `Add webhook retries (#482)`
and PR #482. The PR has a title, a body and labels — a human wrote it for other
humans. The commit has none of that. So we keep the PR and drop the commit.
See `_dedupe` in [collect.py](src/changelog_gen/collect.py).

**2. Why must every generated sentence cite `source_ids`?**
Two reasons, and the second is the real one:
- *Review*: the PR diff links prose back to the commits it came from.
- *Anti-hallucination*: if the model cites `#999` and we never gave it `#999`,
  it invented something. We reject the whole response and retry. This is the
  cheapest, highest-value guard in the project — see `unknown_source_ids` in
  [models.py](src/changelog_gen/models.py) and its tests.

**3. Why one API call per release, not one per change?**
Cheaper, obviously. But also *better*: the model can only merge "add CSV export"
and "stream CSV export to avoid OOM" into a single sentence if it sees them
together.

---

## 4. What's built vs. what isn't

| Piece | Status | Notes |
|---|---|---|
| Package skeleton, CLI, packaging | ✅ Done | `changelog-gen --help` works |
| `.changelog.yml` config loading | ✅ Done | All defaults sane; zero-config runs |
| Git commit collector | ✅ Done | Tested against a real temp repo |
| GitHub PR collector | ✅ Done | Degrades to commits-only if no token/network |
| Commit↔PR de-duplication | ✅ Done | |
| Rules-first classifier | ✅ Done | 13-case corpus in tests |
| GitHub slug detection (incl. SSH aliases) | ✅ Done | Handles `git@github-personal:owner/repo` |
| Markdown + GitHub Release renderers | ✅ Done | Idempotent `CHANGELOG.md` updates |
| CLI flag validation | ✅ Done | `--style` / `--format` typos now error instead of being ignored |
| Prompt templates (system + user) | ✅ Done | Inspect with `--show-prompt` |
| Response validation + hallucination guard | ✅ Done | 8 tests |
| **`AnthropicProvider.complete`** | ⬜ **Next** | ~15 lines. Roadmap in the docstring. |
| **`generate_notes` reliability loop** | ⬜ **Next** | ~25 lines. 4 skipped tests are the spec. |
| Prompt eval file (10 cases) | ⬜ Todo | Phase 1, evening 5 |
| GitHub Action (`action.yml`) | ⬜ Todo | Phase 2 |
| PyPI release | ⬜ Todo | Phase 2 |

---

## 5. ▶ Your next session (do exactly this)

**Build session 4 — the LLM call. Budget: one evening.**

This is the session the whole roadmap points at. Per your own learning plan,
structured outputs is *"the single skill that separates demo-builders from
production-builders."* So you write it, not me.

1. Open [tests/test_llm.py](tests/test_llm.py) and read the four tests below
   the `>>> YOUR TASK <<<` divider. They are a precise spec of the behaviour.
2. Delete the `@pytest.mark.skip` line from the first one.
3. Open [src/changelog_gen/llm.py](src/changelog_gen/llm.py). `AnthropicProvider.complete`
   and `generate_notes` each have a numbered roadmap in their docstring.
4. Implement until `pytest -q` is green with zero skips.
5. Then run it for real: `export ANTHROPIC_API_KEY=... && changelog-gen generate --to HEAD --no-github`

**You'll know you're done when:** all 82 tests pass, and `generate` produces a
changelog you'd actually publish.

**Want me to write it instead, or pair on it?** Just say so — but read the
tests first either way; they're where the design lives.

After that: Phase 1 evening 5 = run it on 2 friends' repos, collect ugly commit
messages into the test corpus, tune the prompt. See [TODO.md](TODO.md).

---

## 6. How changes land (the git flow)

Nothing is ever committed to `main`. Work happens on a feature branch and lands
via a PR into `feature/dev-integration`, which is where you verify it before
promoting to prod. That review gate is the whole point.

```bash
git switch -c feature/whatever
# ... work, commit ...
python3 scripts/open_pr.py            # pushes, then opens a pre-filled PR form
```

**Why a script instead of `gh pr create`?** The `gh` CLI on this machine is
signed in as a different GitHub account (reserved for other work) and has no
write access here, so `gh pr create` returns *"must be a collaborator"*.

`git push` still works, because that authenticates over SSH with your own key
via the `github-personal` host alias. So the script leans on the one PR path
that needs no extra credentials at all: it pushes, then opens GitHub's
**compare URL** with `?expand=1&title=…&body=…`, which is the ordinary "Open a
pull request" form with everything already filled in. You read it and click.

Useful flags: `--base`, `--title`, `--body-file`, `--print-only`, `--no-push`.

Two details worth knowing, because both are easy to get wrong:
- The script carries its own copy of the remote-URL regex so it runs with plain
  `python3`, before any `pip install`. `tests/test_open_pr.py` pins that copy to
  the original in `collect.py`, so the two can't drift apart.
- A body too long for a URL is moved to your clipboard rather than truncated.
  Half a PR description that *looks* complete is worse than none.

---

## 7. Honest deviations from the design docs

Small things I changed and why — so the docs and the code don't quietly drift apart.

| Design doc said | Reality | Why |
|---|---|---|
| Use `uv` | Used `python -m venv` + `pip` | `uv` isn't installed on this machine. Zero-friction alternative; switching later is a 2-minute job (see TODO #0). |
| `model: claude-haiku` | `claude-haiku-4-5` | That's the real, current model ID. $1/$5 per Mtok → ~$0.01 per release, comfortably inside your <$0.05 budget. |
| `prompts/release.j2` | `prompts/system.j2` + `prompts/release.j2` | System and user prompts have different lifetimes — the system prompt is stable per-config, the user prompt changes per-release. Separate files make that visible (and make prompt caching possible later). |
| — | Added `templates/` | Render templates kept separate from prompt templates. Different audience, different reviewers. |
| `ChangeItem` fields | Added optional `author`, `url` | Enables "thanks @person" and deep links later. Costs nothing now. |
| Docs as `.docx` | Converted to `.pdf` | You don't have a Word subscription; PDFs open in Preview. Originals stay in git history (`git show 9167815:docs/BRD.docx`). |
| CLI = `generate` only | Added `collect` and `preview` | Design doc §7 says "dump raw JSON — verify on a real repo before going further." These make that step a real command instead of a throwaway script. |

---

## 8. The gate you already committed to

From the BRD, so it's in front of you and not buried in a PDF:

> **6 weeks after the free tool is public: ≥20 signups OR ≥10 active repos.**
> Otherwise archive with a written retro and move to the next idea.
> Do not extend the deadline.

Also from the phase plan, and the part that's easiest to skip:
**one distribution hour per week is not optional.** Two build sessions + one
hour of showing someone. A repo nobody knows about isn't a product.
