# 04 — Config truth

**What to build:** a configuration that runs the design that was actually
locked. Today the settings on disk disagree with the locked gate configuration
in four places, and one of the gaps makes a model cost zero dollars in every
report.

**Blocked by:** 01.

**Status:** ready-for-agent

## Why

The locked gate configuration (see `.scratch/gate-config-lock/map.md`) is
kimi-k3 + grok-4.5 + gpt-5.6-sol, 2-of-3, sol on flex. The panel on disk is
opus-4-8 + opus-4-8 + grok-4.5. The iteration cap on disk is 5; the locked value
is 10. Nobody currently knows which configuration the next pilot would run.

The dangerous gap is pricing. An unpinned `(model, route)` pair costs `0.0` and
emits one warning to stdout. A judge or panel seat on an unpinned route would
run at an apparently free price, and `--max-cost` would not see it.

## What to build

- The validity panel matches the locked configuration.
- The iteration cap matches the locked configuration. Do NOT pick a new value
  here — ticket 09 builds the instrumentation that decides it later.
- Every model that any panel, roster or judge can reach has a pinned entry in
  the price table for every route it can take. `openai/gpt-5.6-terra-pro`
  currently has an OpenRouter entry only, and the plan routes it through a
  native batch.
- A check that fails loudly, at preflight, when a configured model has no
  pinned price for the route it will take. A warning printed after the money is
  spent is not a check.

## Warnings

Changing the panel changes the config fingerprint, so every existing run
directory will refuse to resume. That is the fingerprint gate working as
designed. Do not add a bypass; the `--force` flag already exists for the
deliberate case.

Do not change `GENERATOR_MODEL`. It is already the native `claude-opus-4-8`
identifier and already routes to the Anthropic batch.

## Acceptance criteria

- [ ] The validity panel, the vote count, the quorum and the iteration cap match
      the locked gate configuration, and the map records that they now agree.
- [ ] Every model reachable from a panel, roster or judge setting has a pinned
      price for every route it can take.
- [ ] Preflight fails, before any request is submitted, when a configured model
      lacks a pinned price for its route.
- [ ] A test covers the preflight failure with an unpinned model.
- [ ] `uv run python -m pytest mask_off -q` passes.
