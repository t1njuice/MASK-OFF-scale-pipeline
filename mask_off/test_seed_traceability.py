"""Self-check: every artifact can say which seed corpus it came from.

The v1 half of this file covered `pipeline.py`'s CSV writers and artifact
naming. It went with ticket 03; `source_name` is the part the frozen path
still uses, and `seeds.Seed.source` carries its result onto every item.

Run: python -m mask_off.test_seed_traceability
"""

from pathlib import Path

from .seeds import source_name


def demo():
    assert source_name(Path("./kimi_100")) == "kimi_100"
    assert source_name(Path("grok_omission2")) == "grok_omission2"
    # cmp/ leaf names are not unique on their own, so the prefix is kept.
    assert source_name(Path("cmp/kimi-k3")) == "cmp/kimi-k3"
    # A path pointing straight at the seeds dir reports its behavior, not "seeds".
    assert source_name(Path("kimi_100/scenarios/seeds")) == "kimi_100"
    assert source_name(Path("cmp/grok-4.5/scenarios/seeds")) == "cmp/grok-4.5"
    print("ok")


if __name__ == "__main__":
    demo()
