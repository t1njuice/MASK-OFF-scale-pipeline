# 03 — Terra and flex routing facts

Type: research
Status: resolved

## Question

What are the verified facts for the OpenAI-seat routing decision?

1. Is gpt-5.6-terra-pro callable on the native OpenAI API, and does it support service_tier=flex? Same for gpt-5.6-sol.
2. Exact current prices: terra native sync, terra flex, sol flex — for the config.PRICES pin (format: in/out/cached_in per MTok).
3. Flex failure behavior: the 429 semantics, recommended retry pattern, and any documented timeout guidance.
4. Does flex support the same request features the gate uses (structured output, reasoning effort control)?

## Answer

Checked 2026-08-13 against the official OpenAI platform docs. Note: `platform.openai.com/docs/...` now 301-redirects to `developers.openai.com/api/docs/...` — same first-party docs.

### 1. Native API availability and flex support

- **`gpt-5.6-terra-pro` is NOT a native OpenAI API model id.** Its model page (`https://developers.openai.com/api/docs/models/gpt-5.6-terra-pro`) returns 404; the official models listing (`https://developers.openai.com/api/docs/models`) shows only `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` in the 5.6 family; the name appears nowhere on the pricing page (`https://developers.openai.com/api/docs/pricing`). The "terra-pro" id exists on third-party routers (OpenRouter `openai/gpt-5.6-terra-pro`, Bedrock); the claim that it is "terra with reasoning.mode=pro" is **unverified** against any primary OpenAI source. Flex for terra-pro is therefore moot — the combination does not exist in the docs.
- **`gpt-5.6-terra` (non-pro) is native and flex-eligible**: it appears in the pricing page's Flex table (`https://developers.openai.com/api/docs/pricing`).
- **`gpt-5.6-sol`: yes native, yes flex.** Model page (`https://developers.openai.com/api/docs/models/gpt-5.6-sol`) confirms Chat Completions, Responses, and Batch; 1,050,000-token context (922K max input / 128K max output). It appears in the Flex pricing table, and the flex guide (`https://developers.openai.com/api/docs/guides/flex-processing`) defines flex-supported models as those listed there.

### 2. Prices per MTok (in / out / cached_in), source `https://developers.openai.com/api/docs/pricing`

| Model / tier | Input | Cached input | Output |
|---|---|---|---|
| gpt-5.6-terra-pro (any tier) | **unverified — no published price; model absent from pricing page** | — | — |
| gpt-5.6-terra standard sync | $2.00 | $0.20 | $12.00 |
| gpt-5.6-terra flex | $1.00 | $0.10 | $6.00 |
| gpt-5.6-sol standard sync | $5.00 | $0.50 | $30.00 |
| gpt-5.6-sol flex | $2.50 | $0.25 | $15.00 |

Flex is exactly 50% of standard for both models. Long-context surcharge on the sol model page: prompts >272K input tokens are priced at 2x input / 1.5x output for the full request (`https://developers.openai.com/api/docs/models/gpt-5.6-sol`).

### 3. Flex failure behavior (source: `https://developers.openai.com/api/docs/guides/flex-processing`)

- **429 semantics**: flex may lack capacity, returning `429 Resource Unavailable`; **you are not charged** for these. It signals capacity unavailability, not a rate-limit violation.
- **Recommended retry**: (a) exponential backoff for delay-tolerant workloads, or (b) retry the request with `service_tier: "auto"` to fall back to standard processing.
- **Timeout guidance**: official SDK default timeout is 10 minutes; the guide's examples raise it to 15 minutes (`timeout=900.0` in Python) because flex responses are slower.
- **Scope**: flex applies to Responses and Chat Completions only (not Batch), via `service_tier: "flex"`; beta with limited model availability.

### 4. Structured output and reasoning effort under flex

- The flex guide documents **no feature restrictions** — nothing excluding structured outputs or reasoning-effort control; only documented limits are beta status, limited models, Responses/Chat Completions only, slower responses, and 429s.
- The sol and terra model pages list `structured_outputs` as supported and reasoning effort levels none/low/medium(default)/high/xhigh/max, with no tier caveat (`https://developers.openai.com/api/docs/models/gpt-5.6-sol`, `.../gpt-5.6-terra`).
- Caveat: this is "no documented limitation," not an explicit per-tier guarantee — the docs do not address feature availability by service tier.
