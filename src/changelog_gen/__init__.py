"""changelog_gen — turn Git history into publishable release notes.

The pipeline is deliberately boring everywhere except one step:

    collect  ->  classify  ->  [LLM rewrite]  ->  render

Everything except the LLM step is plain deterministic Python, so it can be
unit-tested and reasoned about. The LLM does exactly one job: rewrite grouped
facts into customer-facing prose, returning JSON we validate against a schema.
"""

__version__ = "0.1.0"
