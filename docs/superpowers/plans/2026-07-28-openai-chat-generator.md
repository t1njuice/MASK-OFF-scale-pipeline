# OpenAI Chat Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the generator on `openai/gpt-5.5` through sequential Chat
Completions with 24-hour prompt caching, then continue through the unchanged
Anthropic target and reviewer batches.

**Architecture:** Keep `mask_off.llm.run_batch(...)` as the single transport
entry point and preserve its `{custom_id: response_or_none}` contract. Branch
inside it on the explicit `openai/` model prefix; OpenAI calls run one at a time
and Anthropic requests continue through the current Message Batches code.

**Tech Stack:** Python 3.13, `openai>=2.40.0`, `anthropic>=0.96.0`, stdlib
`hashlib` and `unittest`, Rich progress.

## Global Constraints

- Use `openai/gpt-5.5` only for the generator.
- Keep targets and reviewer on their current Anthropic models.
- Use `client.chat.completions.create(...)`, never the OpenAI Batch API.
- Execute OpenAI generator requests sequentially.
- Set `prompt_cache_retention="24h"` and use a deterministic cache key.
- Do not add local response caching, concurrency, provider classes, or a new
  dependency.
- Preserve existing Anthropic batch polling, cancellation, caching, and retry
  behavior.
- Do not stage or alter unrelated working-tree changes.
- Do not run paid smoke tests without explicit user approval.

---

### Task 1: OpenAI request, response, and usage shapes

**Files:**

- Create: `test_llm_openai.py`
- Modify: `mask_off/llm.py:1-103`
- Modify: `mask_off/config.py:36`
- Modify: `mask_off/generator.py:131`
- Modify: `test_generator.py:7-16`

**Interfaces:**

- Consumes: `message_params(model, effort, system, user, max_tokens, thinking)`
- Produces: `openai_client()`, provider-aware `message_params(...)`,
  `text_of(...)`, and `usage_summary_of(...)`
- Preserves: Anthropic parameter and usage shapes

- [ ] **Step 1: Write the failing request and response tests**

Create `test_llm_openai.py` with:

```python
import unittest
from types import SimpleNamespace

from mask_off import config
from mask_off.llm import message_params, text_of, usage_summary_of


def openai_response(text: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(
            prompt_tokens=2006,
            completion_tokens=300,
            prompt_tokens_details=SimpleNamespace(
                cached_tokens=1920,
                cache_write_tokens=64,
            ),
        ),
    )


class OpenAIShapeTests(unittest.TestCase):
    def test_openai_params_use_chat_and_prompt_cache(self):
        params = message_params(
            "openai/gpt-5.5",
            "high",
            "stable system",
            "changing user",
            4096,
            {"type": "adaptive"},
        )
        same = message_params(
            "openai/gpt-5.5",
            "high",
            "stable system",
            "another user",
            4096,
            None,
        )
        changed = message_params(
            "openai/gpt-5.5",
            "high",
            "changed system",
            "changing user",
            4096,
            None,
        )

        self.assertEqual(params["model"], "openai/gpt-5.5")
        self.assertEqual(
            params["messages"],
            [
                {"role": "developer", "content": "stable system"},
                {"role": "user", "content": "changing user"},
            ],
        )
        self.assertEqual(params["reasoning_effort"], "high")
        self.assertEqual(params["max_completion_tokens"], 4096)
        self.assertEqual(params["prompt_cache_retention"], "24h")
        self.assertEqual(params["prompt_cache_key"], same["prompt_cache_key"])
        self.assertNotEqual(params["prompt_cache_key"], changed["prompt_cache_key"])
        self.assertNotIn("thinking", params)

    def test_openai_text_and_usage_map_to_existing_contract(self):
        response = openai_response('{"ok": true}')

        self.assertEqual(text_of(response), '{"ok": true}')
        self.assertEqual(
            usage_summary_of(response),
            {
                "input_tokens": 2006,
                "output_tokens": 300,
                "cache_creation_input_tokens": 64,
                "cache_read_input_tokens": 1920,
            },
        )

    def test_anthropic_params_remain_unchanged(self):
        params = message_params(
            "claude-opus-4-8",
            "high",
            "system",
            "user",
            4096,
            {"type": "adaptive"},
        )

        self.assertEqual(params["model"], "claude-opus-4-8")
        self.assertEqual(params["system"][0]["text"], "system")
        self.assertEqual(
            params["system"][0]["cache_control"],
            {"type": "ephemeral", "ttl": "1h"},
        )
        self.assertEqual(params["messages"], [{"role": "user", "content": "user"}])
        self.assertEqual(params["output_config"], {"effort": "high"})

    def test_generator_defaults_to_openai(self):
        self.assertEqual(config.GENERATOR_MODEL, "openai/gpt-5.5")


if __name__ == "__main__":
    unittest.main()
```

Update the two request-layout lines in
`GeneratorRequestTests.test_first_attempt_renders_authoritative_seed_block`:

```python
params = request["params"]
system = params["messages"][0]["content"]
user = params["messages"][1]["content"]
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
uv run python -m unittest test_llm_openai.py test_generator.py
```

Expected: failures because the generator is still Claude-shaped and OpenAI
cache, response, and usage handling do not exist.

- [ ] **Step 3: Implement the minimal provider-aware shapes**

In `mask_off/config.py`:

```python
GENERATOR_MODEL = "openai/gpt-5.5"
GENERATOR_EFFORT = "high"
```

Change the `mask_off/llm.py` module docstring to:

```python
"""Thin OpenAI Chat Completions and Anthropic Message Batches helpers."""
```

Add `import hashlib` beside the stdlib imports and `import openai` beside
`import anthropic`. Keep the Rich and `.config` imports unchanged.

Replace the client globals/functions with:

```python
_client = None
_openai_client = None


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=1, timeout=config.TIMEOUT)
    return _client


def openai_client():
    global _openai_client
    if _openai_client is None:
        _openai_client = openai.OpenAI(max_retries=1, timeout=config.TIMEOUT)
    return _openai_client
```

Change the `build_gen_request(...)` docstring in `mask_off/generator.py` to:

```python
    """A generator request for the configured provider."""
```

Replace `text_of(...)` with:

```python
def text_of(response) -> str:
    """Return visible text from either provider response."""
    if hasattr(response, "choices"):
        return (response.choices[0].message.content or "").strip()
    return "".join(
        b.text for b in response.content if getattr(b, "type", None) == "text"
    ).strip()
```

Replace `usage_summary_of(...)` with:

```python
def usage_summary_of(response) -> dict:
    usage = getattr(response, "usage", None)
    if hasattr(usage, "prompt_tokens"):
        details = getattr(usage, "prompt_tokens_details", None)
        return {
            "input_tokens": usage.prompt_tokens or 0,
            "output_tokens": usage.completion_tokens or 0,
            "cache_creation_input_tokens": (
                getattr(details, "cache_write_tokens", 0) or 0
            ),
            "cache_read_input_tokens": getattr(details, "cached_tokens", 0) or 0,
        }
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": (
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        ),
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
```

Insert this branch as the first body lines of `message_params(...)`. Keep the
current Anthropic `params = dict(...)`, its 1-hour cost rationale comment, the
`thinking` handling, and its return unchanged after the branch:

```python
def message_params(model, effort, system, user, max_tokens, thinking) -> dict:
    if model.startswith("openai/"):
        api_model = model.removeprefix("openai/")
        if not api_model:
            raise ValueError("OpenAI model ID cannot be empty")
        cache_key = hashlib.sha256(
            f"{api_model}\0{system}".encode("utf-8")
        ).hexdigest()
        return {
            "model": model,
            "messages": [
                {"role": "developer", "content": system},
                {"role": "user", "content": user},
            ],
            "reasoning_effort": effort,
            "max_completion_tokens": max_tokens,
            "prompt_cache_key": cache_key,
            "prompt_cache_retention": "24h",
        }

```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
uv run python -m unittest test_llm_openai.py test_generator.py
```

Expected: all request, response, usage, cache, and generator prompt tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add mask_off/config.py mask_off/generator.py mask_off/llm.py test_generator.py test_llm_openai.py
git commit -m "Add OpenAI generator request shapes"
```

---

### Task 2: Sequential OpenAI transport and Anthropic batch handoff

**Files:**

- Modify: `test_llm_openai.py`
- Modify: `mask_off/llm.py:162-231`

**Interfaces:**

- Consumes: existing `{custom_id, params}` requests
- Produces: unchanged `{custom_id: response_or_none}` results
- Guarantees: all OpenAI generator calls finish before the next Anthropic
  target or reviewer batch starts

- [ ] **Step 1: Write failing sequential and handoff tests**

Extend `test_llm_openai.py`:

```python
from unittest.mock import patch

import openai
from rich.progress import Progress

from mask_off.llm import run_batch


class FakeOpenAICompletions:
    def __init__(self, outcomes, events):
        self.outcomes = list(outcomes)
        self.events = events

    def create(self, **params):
        self.events.append(("openai", params["messages"][-1]["content"]))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeAnthropicBatches:
    def __init__(self, events, message):
        self.events = events
        self.message = message
        self.requests = []

    def create(self, requests):
        self.events.append(("anthropic", "create"))
        self.requests = requests
        return SimpleNamespace(id="batch-1")

    def retrieve(self, _batch_id):
        return SimpleNamespace(
            processing_status="ended",
            request_counts=SimpleNamespace(
                succeeded=len(self.requests),
                errored=0,
                canceled=0,
                expired=0,
            ),
        )

    def results(self, _batch_id):
        return [
            SimpleNamespace(
                custom_id=request["custom_id"],
                result=SimpleNamespace(type="succeeded", message=self.message),
            )
            for request in self.requests
        ]


def openai_request(custom_id: str, user: str):
    return {
        "custom_id": custom_id,
        "params": message_params(
            "openai/gpt-5.5", "high", "stable system", user, 256, None
        ),
    }


def anthropic_request(custom_id: str):
    return {
        "custom_id": custom_id,
        "params": message_params(
            "claude-opus-4-8", "high", "system", "review", 256, None
        ),
    }


class TransportHandoffTests(unittest.TestCase):
    def test_openai_is_sequential_before_anthropic_reviewer_batch(self):
        events = []
        first = openai_response("first")
        second = openai_response("second")
        reviewer_message = object()
        completions = FakeOpenAICompletions([first, second], events)
        batches = FakeAnthropicBatches(events, reviewer_message)
        fake_openai = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        fake_anthropic = SimpleNamespace(
            messages=SimpleNamespace(batches=batches)
        )

        with (
            patch("mask_off.llm.openai_client", return_value=fake_openai),
            patch("mask_off.llm.client", return_value=fake_anthropic),
            Progress(disable=True) as progress,
        ):
            generated = run_batch(
                [openai_request("gen-1", "first"), openai_request("gen-2", "second")],
                "Generator",
                progress,
            )
            reviewed = run_batch(
                [anthropic_request("review-1")],
                "Reviewer",
                progress,
            )

        self.assertEqual(
            events,
            [("openai", "first"), ("openai", "second"), ("anthropic", "create")],
        )
        self.assertIs(generated["gen-1"], first)
        self.assertIs(generated["gen-2"], second)
        self.assertIs(reviewed["review-1"], reviewer_message)

    def test_one_openai_failure_does_not_block_success_or_reviewer_batch(self):
        events = []
        success = openai_response("success")
        reviewer_message = object()
        completions = FakeOpenAICompletions(
            [openai.OpenAIError("boom"), success],
            events,
        )
        batches = FakeAnthropicBatches(events, reviewer_message)
        fake_openai = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        fake_anthropic = SimpleNamespace(
            messages=SimpleNamespace(batches=batches)
        )

        with (
            patch("mask_off.llm.openai_client", return_value=fake_openai),
            patch("mask_off.llm.client", return_value=fake_anthropic),
            Progress(disable=True) as progress,
        ):
            generated = run_batch(
                [openai_request("gen-1", "bad"), openai_request("gen-2", "good")],
                "Generator",
                progress,
            )
            reviewed = run_batch(
                [anthropic_request("review-1")],
                "Reviewer",
                progress,
            )

        self.assertIsNone(generated["gen-1"])
        self.assertIs(generated["gen-2"], success)
        self.assertIs(reviewed["review-1"], reviewer_message)
        self.assertEqual(events[-1], ("anthropic", "create"))
```

- [ ] **Step 2: Run the transport tests and verify RED**

Run:

```bash
uv run python -m unittest test_llm_openai.TransportHandoffTests
```

Expected: failure because `run_batch(...)` still submits OpenAI-shaped requests
to Anthropic Message Batches.

- [ ] **Step 3: Add the sequential branch before existing batch code**

In `run_batch(...)`, keep the existing `if not requests: return {}` and replace
the current `if progress is None` block with the validation, progress setup,
and OpenAI branch below. Leave the Anthropic code beginning with
`batches = client().messages.batches` unchanged after it:

```python
    models = [request["params"]["model"] for request in requests]
    providers = {
        "openai" if model.startswith("openai/") else "anthropic"
        for model in models
    }
    if len(providers) != 1:
        raise ValueError("one run_batch call cannot mix OpenAI and Anthropic")
    if "openai" in providers and any(model == "openai/" for model in models):
        raise ValueError("OpenAI model ID cannot be empty")

    if progress is None:
        with batch_progress() as progress:
            return run_batch(requests, label, progress)

    if "openai" in providers:
        task = progress.add_task(label, total=len(requests))
        completions = openai_client().chat.completions
        out = {}
        try:
            for request in requests:
                params = dict(request["params"])
                params["model"] = params["model"].removeprefix("openai/")
                try:
                    out[request["custom_id"]] = completions.create(**params)
                except openai.OpenAIError as exc:
                    progress.console.print(
                        f"{request['custom_id']}: {exc}",
                        markup=False,
                        highlight=False,
                    )
                    out[request["custom_id"]] = None
                finally:
                    progress.update(task, advance=1, refresh=True)
        finally:
            progress.remove_task(task)
        return out
```

Leave all Anthropic code after this branch unchanged. Update the `run_batch`
docstring to state that OpenAI requests are sequential Chat Completions while
Anthropic requests use Message Batches.

- [ ] **Step 4: Run the focused transport tests and verify GREEN**

Run:

```bash
uv run python -m unittest test_llm_openai.py
```

Expected: all OpenAI transport tests pass, including the explicit
OpenAI-generator-to-Anthropic-reviewer event ordering.

- [ ] **Step 5: Commit Task 2**

```bash
git add mask_off/llm.py test_llm_openai.py
git commit -m "Route OpenAI generator calls sequentially"
```

---

### Task 3: Dual-provider preflight and safe artifact names

**Files:**

- Modify: `test_llm_openai.py`
- Modify: `mask_off/pipeline.py:18-26`
- Modify: `mask_off/pipeline.py:59-61`
- Modify: `mask_off/pipeline.py:952-955`
- Modify: `mask_off/pipeline.py:1178-1216`

**Interfaces:**

- Consumes: `config.GENERATOR_MODEL`, `client()`, and `openai_client()`
- Produces: `preflight() -> bool` after checking every active provider
- Preserves: existing Anthropic authentication diagnostics

- [ ] **Step 1: Write failing preflight and artifact-slug tests**

Extend `test_llm_openai.py`:

```python
from unittest.mock import Mock

from mask_off import pipeline


class PipelineProviderTests(unittest.TestCase):
    def test_openai_model_slug_is_artifact_safe(self):
        self.assertEqual(
            pipeline.model_slug("openai/gpt-5.5"),
            "openai-gpt-5.5",
        )

    def test_preflight_checks_openai_then_anthropic(self):
        events = []
        openai_create = Mock(
            side_effect=lambda **_params: events.append("openai")
        )
        anthropic_create = Mock(
            side_effect=lambda **_params: events.append("anthropic")
        )
        fake_openai = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=openai_create))
        )
        fake_anthropic = SimpleNamespace(
            messages=SimpleNamespace(create=anthropic_create)
        )

        with (
            patch.object(pipeline, "openai_client", return_value=fake_openai),
            patch.object(pipeline, "client", return_value=fake_anthropic),
        ):
            self.assertTrue(pipeline.preflight())

        self.assertEqual(events, ["openai", "anthropic"])
        self.assertEqual(
            openai_create.call_args.kwargs["model"],
            "gpt-5.5",
        )
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
uv run python -m unittest test_llm_openai.PipelineProviderTests
```

Expected: the slug assertion fails and `pipeline.openai_client` does not exist.

- [ ] **Step 3: Implement the one-line slug fix**

Replace `model_slug(...)` with:

```python
def model_slug(model: str) -> str:
    """Return an artifact-safe model label."""
    return model.replace("/", "-").removeprefix("claude-") or model
```

- [ ] **Step 4: Add the OpenAI preflight before the existing Anthropic preflight**

Add `import openai` and import `openai_client` from `.llm`.

Add the OpenAI credentials message beside `_NO_CREDS_MSG`:

```python
_NO_OPENAI_CREDS_MSG = (
    "ERROR: no OpenAI credentials found. Set OPENAI_API_KEY and retry."
)
```

At the start of `preflight()`, before the existing Anthropic client block, add:

```python
    if config.GENERATOR_MODEL.startswith("openai/"):
        try:
            oai = openai_client()
        except openai.OpenAIError as exc:
            print(f"{_NO_OPENAI_CREDS_MSG}\n  ({exc})", file=sys.stderr)
            return False
        try:
            oai.chat.completions.create(
                model=config.GENERATOR_MODEL.removeprefix("openai/"),
                max_completion_tokens=16,
                messages=[{"role": "user", "content": "ping"}],
            )
        except openai.AuthenticationError as exc:
            print(
                "ERROR: OpenAI rejected OPENAI_API_KEY (401).\n"
                f"  ({exc})",
                file=sys.stderr,
            )
            return False
        except openai.APIError as exc:
            print(
                f"ERROR during OpenAI preflight call (API/network): {exc}",
                file=sys.stderr,
            )
            return False
```

Do not change the following Anthropic credential construction, ping, or error
handling. It must run after the OpenAI ping and remain the function's source of
the final `True`.

- [ ] **Step 5: Run all focused offline verification**

Run:

```bash
uv run python -m unittest test_llm_openai.py test_generator.py
uv run python test_pipeline_waves.py
uv run python -m compileall mask_off
git diff --check
```

Expected: all tests and compilation pass; no command makes an API request.

- [ ] **Step 6: Inspect the scoped diff and preserve unrelated edits**

Run:

```bash
git diff HEAD~2 -- mask_off/config.py mask_off/generator.py mask_off/llm.py mask_off/pipeline.py test_generator.py test_llm_openai.py
git status --short
```

Confirm the implementation touches only the six planned files and leaves all
pre-existing modifications and untracked artifacts intact.

- [ ] **Step 7: Commit Task 3**

```bash
git add mask_off/pipeline.py test_llm_openai.py
git commit -m "Validate OpenAI generator preflight"
```

No paid smoke run is part of this plan.
