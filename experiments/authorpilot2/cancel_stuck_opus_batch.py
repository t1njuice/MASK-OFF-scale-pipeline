"""User-approved queue escape (2026-08-12): the opus author batch for author
pilot 2 sat in the Anthropic queue with 0 of 9 requests completed. Cancel it
(nothing to harvest) and rerun the opus author via OpenRouter sync instead.

Only cancels msgbatch_019jA2Wt7rFwVpBPZeV6i9KW — the author-pilot-2 opus
batch (created 2026-08-12 09:14Z, 9 requests). The live gatepilot batches
from 07:21Z are untouched.
"""

from dotenv import load_dotenv

load_dotenv("../../.env")
import anthropic  # noqa: E402

BATCH_ID = "msgbatch_019jA2Wt7rFwVpBPZeV6i9KW"

c = anthropic.Anthropic()
b = c.messages.batches.retrieve(BATCH_ID)
print("before:", b.processing_status, b.request_counts)
if b.request_counts.succeeded > 0:
    print("batch has completed requests now — NOT canceling; harvest instead")
elif b.processing_status == "ended":
    print("batch already ended — nothing to cancel")
else:
    b = c.messages.batches.cancel(BATCH_ID)
    print("after cancel:", b.processing_status, b.request_counts)
