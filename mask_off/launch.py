"""What a run needs before its first request: a credential, a stamp, a pool.

Extracted from the retired v1 `pipeline.py`, which every live module imported
for exactly these three functions.
"""

import datetime
import os
import random
import sys
import warnings
from pathlib import Path

import anthropic

from . import config, panel, pricing
from .llm import client
from .seeds import load_seeds

_NO_CREDS_MSG = (
    "ERROR: no Anthropic credentials found. Set ANTHROPIC_API_KEY or run "
    "`ant auth login`."
)


def run_timestamp() -> str:
    """UTC stamp, date and clock split so it reads at a glance: 2026-07-26_182400Z.

    Seconds are kept: two runs started in the same minute would otherwise write to
    the same names and the second would silently overwrite the first.
    """
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d_%H%M%SZ")


def select_seeds(n: int, seeds_path: Path) -> list:
    """The launch pool for a run: sorted, then sampled.

    Split out of the run loop so a caller can name artifacts after the seeds
    that will actually run. With SAMPLE_SEED = None the sample is OS-entropy
    random, so it must be drawn once and shared — drawing twice would put one
    set in the filename and run a different one.
    """
    seed_pool = load_seeds(Path(seeds_path))
    if n > len(seed_pool):
        warnings.warn(
            f"asked for {n} seeds but the pool only has {len(seed_pool)}; "
            f"running all of them",
            stacklevel=2,
        )
        n = len(seed_pool)
    # sorted() first: load order must not change which seeds a fixed
    # SAMPLE_SEED picks. random.Random(None) seeds from OS entropy.
    return random.Random(config.SAMPLE_SEED).sample(
        sorted(seed_pool, key=lambda s: s.name), n
    )


def preflight() -> bool:
    """True when a run may submit its first request.

    Checks the pinned prices and the credentials, in that order: the price
    check costs nothing and catches the failure that money makes permanent.
    """
    # 0) Every reachable (model, route) must have a pinned price. An unpinned
    #    pair costs 0.0 in every report, so --max-cost cannot see it.
    gaps = pricing.unpinned()
    if gaps:
        print(
            "ERROR: these configured (model, route) pairs have no pinned price "
            "in config.PRICES, so they would cost $0 in every report and "
            "--max-cost could not see them:\n"
            + "\n".join(f"  {model} on {route}" for model, route in gaps)
            + "\nPin each one before running.",
            file=sys.stderr,
        )
        return False
    # 1) The panels whose labels key results must label their seats uniquely.
    #    A roster seat's label is in its request ids and its response keys, so
    #    two seats under one label share a cache entry: one model's answer is
    #    served to both and the other is paid for but never sampled. A judge's
    #    label keys its judgments and its block in the summary, so a duplicate
    #    merges two judges into one rate.
    #    VALIDITY_PANEL is exempt on purpose: a gate vote is identified by its
    #    slot (`__vote{i}`), never by a label, so three votes from one model is
    #    a legal configuration and always was.
    for name in ("TARGET_PANEL", "JUDGE_PANEL"):
        dupes = panel.duplicate_labels(getattr(config, name))
        if dupes:
            print(
                f"ERROR: config.{name} reuses the seat label(s) {dupes}. A "
                f"label is what a seat's request ids and its reported results "
                f"key on, so a duplicate silently merges two seats into one.",
                file=sys.stderr,
            )
            return False
    # 2) OpenRouter-routed models, in ANY role, need their own key. Derived
    #    from the same reachable set the price check uses: a hand-built list
    #    silently omitted the thermometer, seedgen, judge and smoke models,
    #    and only caught them while a roster model happened to share a slug.
    openrouter_models = sorted({
        model
        for model in pricing.configured_models()
        if pricing.reachable_routes(model) & {"openrouter_sync"}
    })
    if openrouter_models and not os.environ.get("OPENROUTER_API_KEY"):
        print(
            f"ERROR: {openrouter_models} route through OpenRouter but "
            f"OPENROUTER_API_KEY is not set.",
            file=sys.stderr,
        )
        return False
    # 3) Anthropic credentials are needed only if something actually routes
    #    there. Derived the same way the OpenRouter check above is, and for
    #    the same reason: the probe used to be hardwired to GENERATOR_MODEL on
    #    the Anthropic client, which held only while the generator was a
    #    claude-* id. A non-Claude generator — the ablation table's
    #    cross-generator row — 404s a reachable model and refuses to start.
    anthropic_models = sorted({
        model
        for model in pricing.configured_models()
        if pricing.reachable_routes(model) & {"anthropic_batch", "anthropic_sync"}
    })
    if not anthropic_models:
        return True
    try:
        anthropic_client = client()
    except anthropic.AnthropicError as exc:
        print(f"{_NO_CREDS_MSG}\n  ({exc})", file=sys.stderr)
        return False
    # 4) Make one cheap call to prove the credential actually works. Probe a
    #    model that is genuinely on the Anthropic route, not whichever model
    #    happens to be the generator.
    try:
        anthropic_client.messages.create(
            model=anthropic_models[0],
            max_tokens=16,
            messages=[{"role": "user", "content": "ping"}],
        )
        return True
    except anthropic.AuthenticationError as exc:
        print(
            "ERROR: Anthropic rejected the credentials (401). Check "
            f"ANTHROPIC_API_KEY or your `ant auth login` profile.\n  ({exc})",
            file=sys.stderr,
        )
        return False
    except anthropic.APIError as exc:
        print(f"ERROR during preflight call (API/network): {exc}", file=sys.stderr)
        return False
    except anthropic.AnthropicError as exc:
        print(f"{_NO_CREDS_MSG}\n  ({exc})", file=sys.stderr)
        return False
    except TypeError as exc:
        # The SDK raises TypeError when no auth method resolves (no key set).
        message = str(exc).lower()
        if "authentication" in message or "api_key" in message:
            print(f"{_NO_CREDS_MSG}\n  ({exc})", file=sys.stderr)
        else:
            print(f"ERROR during preflight call: {exc}", file=sys.stderr)
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR during preflight call: {exc}", file=sys.stderr)
        return False
