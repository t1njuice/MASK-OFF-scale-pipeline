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

from . import config
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

    Checks credentials only. Ticket 04 adds the pinned-price check here.
    """
    # 0) OpenRouter-routed models (any role) need their own key.
    openrouter_models = [
        model
        for model in [*config.TARGET_MODELS, config.GENERATOR_MODEL,
                      *(config.VALIDITY_PANEL or [config.VALIDITY_MODEL])]
        if not model.startswith("claude") and not model.startswith("openai/")
    ]
    if openrouter_models and not os.environ.get("OPENROUTER_API_KEY"):
        print(
            f"ERROR: {sorted(set(openrouter_models))} route through OpenRouter "
            f"but OPENROUTER_API_KEY is not set.",
            file=sys.stderr,
        )
        return False
    # 1) Construct the client — this is where a missing or unresolvable
    #    credential fails.
    try:
        anthropic_client = client()
    except anthropic.AnthropicError as exc:
        print(f"{_NO_CREDS_MSG}\n  ({exc})", file=sys.stderr)
        return False
    # 2) Make one cheap call to prove the credential actually works.
    try:
        anthropic_client.messages.create(
            model=config.GENERATOR_MODEL,
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
