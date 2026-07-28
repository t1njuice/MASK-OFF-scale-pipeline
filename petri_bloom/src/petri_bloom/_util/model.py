"""Model utility functions."""

from dataclasses import dataclass

from inspect_ai.model import GenerateConfig, Model, ModelUsage, get_model_info

# Frontier models are routinely absent from the model info database (both
# anthropic/claude-opus-5 and openrouter/x-ai/grok-4.5 report no output limit).
# 8192 is below what a dimensions or scenarios response needs once reasoning
# tokens share the same budget, and the overflow surfaces as a truncated tool
# call rather than an error naming the limit.
_DEFAULT_MAX_TOKENS = 32000

# Some model info entries report the context window as `output_tokens` (e.g.
# openrouter/moonshotai/kimi-k3 at 1048576). Requesting that as max_tokens
# leaves no room for the prompt and the provider rejects the call with a 400.
# Cap at a value no single scenario batch needs; raise it if a model genuinely
# supports and requires more output.
_MAX_TOKENS_CAP = 64000


def resolve_max_tokens(model: Model) -> int:
    """Resolve the max output tokens for a model.

    Uses inspect_ai's model info database, capped at `_MAX_TOKENS_CAP` so that
    entries reporting a context window rather than an output limit cannot
    produce an unsatisfiable request. Falls back to a conservative default if
    the model is not found.

    Args:
        model: Model instance to look up.

    Returns:
        Maximum output tokens for the model.
    """
    info = get_model_info(model)
    if info and info.output_tokens:
        return min(info.output_tokens, _MAX_TOKENS_CAP)
    return _DEFAULT_MAX_TOKENS


@dataclass
class RunUsage:
    """Token usage accumulated across the generate calls of one stage."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_cost: float = 0.0

    def record(self, usage: ModelUsage | None) -> None:
        """Add one generate call's usage to the running totals."""
        self.calls += 1
        if usage is None:
            return
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.reasoning_tokens += usage.reasoning_tokens or 0
        self.total_cost += usage.total_cost or 0.0

    def __str__(self) -> str:
        parts = [
            f"{self.calls} calls",
            f"{self.input_tokens:,} in",
            f"{self.output_tokens:,} out",
        ]
        if self.reasoning_tokens:
            parts.append(f"{self.reasoning_tokens:,} reasoning")
        # Providers that don't price the response leave total_cost unset; only
        # report a figure the provider actually returned.
        if self.total_cost:
            parts.append(f"${self.total_cost:.4f}")
        return ", ".join(parts)


def calculate_batch_size(
    num_scenarios: int,
    max_output_tokens: int,
    modality: str,
    config: GenerateConfig | None = None,
    safety_margin: float = 0.8,
) -> tuple[int, int]:
    """Calculate optimal batch size for scenario generation.

    Estimates how many scenarios fit in a single model response based
    on the model's output token limit. When reasoning effort is enabled,
    reduces the usable token budget conservatively.

    Args:
        num_scenarios: Total number of scenarios to generate.
        max_output_tokens: Model's max output token limit.
        modality: `conversation` or `agent` (agent scenarios are larger).
        config: Generation config (used to check reasoning_effort).
        safety_margin: Fraction of usable tokens to actually use (default 0.8).

    Returns:
        Tuple of (batch_size, num_batches).
    """
    # Estimate reasoning overhead from config
    reasoning_reduction = 1.0
    if config and config.reasoning_effort:
        effort = config.reasoning_effort
        reasoning_reduction = {
            "none": 1.0,
            "minimal": 0.9,
            "low": 0.85,
            "medium": 0.75,
            "high": 0.6,
            "xhigh": 0.5,
        }.get(effort, 0.7)

    tokens_per_scenario = 1000 if modality == "agent" else 600
    overhead = 2000

    usable = int((max_output_tokens * reasoning_reduction - overhead) * safety_margin)
    batch_size = max(1, min(usable // tokens_per_scenario, num_scenarios))
    num_batches = (num_scenarios + batch_size - 1) // batch_size

    return batch_size, num_batches
