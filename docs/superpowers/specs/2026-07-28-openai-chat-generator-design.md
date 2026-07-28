# OpenAI Chat Generator Design

## Goal

Use `openai/gpt-5.5` for the generator through synchronous Chat Completions
while preserving Anthropic Message Batches for targets and the reviewer.
OpenAI prompt caching uses a deterministic key and 24-hour retention.

## Scope

- Change `GENERATOR_MODEL` to `openai/gpt-5.5`.
- Keep `GENERATOR_EFFORT = "high"`.
- Keep all target and reviewer model configuration on Anthropic.
- Route model IDs beginning with `openai/` through OpenAI Chat Completions.
- Execute OpenAI requests sequentially, without the OpenAI Batch API.
- Preserve the current request/result contract used by the pipeline.
- Preserve the existing Anthropic Message Batches implementation.
- Sanitize the provider-qualified generator model in artifact filenames.

The design does not add local response caching, concurrent OpenAI calls,
provider classes, or OpenAI target-model support.

## Architecture

`mask_off/llm.py` remains the shared transport boundary. Existing stage request
builders continue producing:

```python
{"custom_id": str, "params": dict}
```

`message_params(...)` builds provider-specific parameters from its existing
arguments:

- `openai/...` models produce Chat Completions parameters.
- Other configured models retain the existing Anthropic Messages parameters.

`run_batch(...)` keeps its public name and return type:

```python
{custom_id: response_or_none}
```

For an OpenAI request set, it makes individual synchronous Chat Completions
calls in request order. For an Anthropic request set, it uses the unchanged
Message Batches flow. A single `run_batch(...)` invocation must contain one
provider; mixed-provider input fails before any request is submitted.

No pipeline stage gets a separate provider implementation.

## OpenAI Request Shape

The `openai/` prefix remains in the internal `params["model"]` value so
`run_batch(...)` can select the provider. The OpenAI branch copies the
parameters and removes the prefix immediately before the API call.

The resulting wire request is:

```python
{
    "model": "gpt-5.5",
    "messages": [
        {"role": "developer", "content": system},
        {"role": "user", "content": user},
    ],
    "reasoning_effort": "high",
    "max_completion_tokens": max_tokens,
    "prompt_cache_key": cache_key,
    "prompt_cache_retention": "24h",
}
```

The cache key is a non-sensitive deterministic digest of the model and system
prompt. Generator requests sharing the same stable prompt therefore share a
cache-routing key. A changed generator prompt produces a different key.

OpenAI prompt caching remains provider-managed. It only produces a hit when
OpenAI's eligibility and exact-prefix requirements are satisfied; no response
is persisted locally.

## Clients and Responses

The existing `client()` remains the Anthropic client. `llm.py` adds one lazy
`openai_client()` using the already-installed `openai` dependency and the
existing timeout setting.

`text_of(...)` supports both response shapes:

- Anthropic: join returned text blocks as today.
- OpenAI: return `choices[0].message.content`, or an empty string when absent.

`usage_summary_of(...)` preserves the existing usage dictionary:

```python
{
    "input_tokens": int,
    "output_tokens": int,
    "cache_creation_input_tokens": int,
    "cache_read_input_tokens": int,
}
```

OpenAI fields map as follows:

- `prompt_tokens` to `input_tokens`
- `completion_tokens` to `output_tokens`
- `prompt_tokens_details.cache_write_tokens` to
  `cache_creation_input_tokens`
- `prompt_tokens_details.cached_tokens` to `cache_read_input_tokens`

The generator does not consume reasoning summaries, so OpenAI thinking-summary
support is outside this change.

## Pipeline Phase Ordering

The existing wave boundary remains authoritative:

1. Build every ready generator request.
2. Execute OpenAI generator requests sequentially and collect the complete
   `{custom_id: response_or_none}` map.
3. Parse generator results and select ready candidates.
4. Submit those candidates through the existing Anthropic target batch.
5. Submit their target results through the existing Anthropic reviewer batch.

The sequential OpenAI path completes before either Anthropic batch starts.
It does not reuse or replace the Anthropic batch client, batch handles, progress
tasks, polling, or cancellation behavior.

The same outer `Progress` display may be reused across phases. The OpenAI phase
owns only its temporary progress task and removes it before returning, so the
target and reviewer batch tasks start with clean state.

## Errors and Preflight

- An empty `openai/` model ID raises `ValueError` before network work.
- Mixed providers in one `run_batch(...)` call raise `ValueError`.
- An individual `openai.OpenAIError` is printed through the existing progress
  console and stored as `None` for that `custom_id`, matching an errored
  Anthropic batch item.
- Missing or invalid credentials fail during preflight.
- Preflight validates both providers required by the configured run: OpenAI for
  the generator and Anthropic for targets/reviewer.
- Existing Anthropic connection retry, polling, cancellation, and failed-item
  behavior remain unchanged.

## Files

- Modify `mask_off/config.py` for the generator model.
- Modify `mask_off/llm.py` for OpenAI request construction, sequential
  transport, response text, and usage mapping.
- Modify `mask_off/pipeline.py` for dual-provider preflight and an artifact-safe
  `openai-gpt-5.5` model slug.
- Add `test_llm_openai.py` for deterministic transport checks.

No dependency or prompt-file changes are required.

## Testing

Development follows a focused red-green cycle in `test_llm_openai.py`:

1. Verify OpenAI parameter construction, prefix removal at dispatch,
   `reasoning_effort`, deterministic cache key, and `24h` retention.
2. Verify sequential request order and the unchanged
   `{custom_id: response_or_none}` result contract using a fake OpenAI client.
3. Verify OpenAI text extraction and cached-token usage mapping.
4. Verify the Anthropic parameter shape remains unchanged.
5. Verify one OpenAI generator phase can finish before the Anthropic target and
   reviewer batch phases use the same `run_batch(...)` entry point, with
   separate clients and correctly returned results.
6. Verify one failed OpenAI generator request becomes `None` while another
   succeeds, allowing its later Anthropic reviewer batch phase to complete.
7. Verify `model_slug("openai/gpt-5.5") == "openai-gpt-5.5"` so run artifacts
   remain in `output/` rather than creating a provider-named subdirectory.

Run:

```bash
uv run python -m unittest test_llm_openai.py
uv run python -m compileall mask_off
```

These checks make no paid API calls. A paid smoke run requires separate user
approval because it invokes both configured providers.

## Acceptance Criteria

- The configured generator model is `openai/gpt-5.5`.
- Generator requests use synchronous Chat Completions, one at a time.
- Every OpenAI generator request includes a stable cache key and `24h`
  retention.
- Generator output and usage attach through the existing parser contract.
- Generated artifact paths contain `openai-gpt-5.5`, never an `openai/`
  directory component.
- Target and reviewer stages still use Anthropic Message Batches.
- Sequential generation completes cleanly before reviewer batching begins.
- Existing Anthropic batch behavior is unchanged.
- The focused tests and package compilation pass without network access.
