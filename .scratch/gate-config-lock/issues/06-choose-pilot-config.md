# 06 — Choose the config to pilot

Type: grilling
Status: resolved
Blocked by: 01, 03, 05, 08

## Question

Which single configuration gets the one confirmation pilot?

Decide with the user, from the replay analysis (01), the routing facts (03), and the prompt-edit decision (05): panel members, quorum rule, OpenAI-seat model and route, and whether the prompt edit is included. The answer names the exact pilot invocation.

## Answer

Decided by the user (2026-08-13), superseding the pilot framing: **no pilot; keep sol**. The locked gate configuration:

- Panel: kimi-k3 + grok-4.5 + gpt-5.6-sol, 2-of-3 quorum, cap 10 iterations.
- OpenAI seat routing: sol on native flex (service_tier=flex, $2.50/$15 = batch price without batch latency), one retry on standard sync after a 429 or timeout.
- Generator: opus-4.8 on anthropic_batch (unchanged).
- Prompt changes from ticket 05 (direction lock + AGREED FAIL header) are in the config.
- Terra rejected for now: replay could not validate it (~half of iterations depend on the unknown seat), and after ticket 08 a lenient terra is a quality risk; without a pilot budget it stays unproven.

Validation of the whole config: user-run test after their architecture changes (see ticket 07).
