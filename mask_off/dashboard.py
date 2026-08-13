"""Where is this pipeline, right now?

Prints one screen per stage. It talks to no provider and holds no lock, so it
is safe against a live run from a second terminal, against a finished run, and
against one that died — every figure comes from an artifact already on disk.
That is the point: a progress bar dies with its process, and these stages run
for hours.

Seed authoring (`mask_off.seedgen`, its own output directory):

    scenarios/seeds/*.md   seeds written      author_log.jsonl   one row per
    <dir>_cheap.jsonl      audit verdicts                        taxonomy row

Stage A and Stage B (`mask_off.scale`, one run directory):

    accepted.jsonl  items accepted so far      run_log.jsonl  every wave
    state.json      target, in flight, yield   cohorts.jsonl  checkpoint rows
    _batches.jsonl  batches submitted          _scale.pid     the live process
    eval/           Stage B grids

    python -m mask_off.dashboard output/scale_x
    python -m mask_off.dashboard --seeds seeds_300
    python -m mask_off.dashboard output/scale_x --seeds seeds_300 --watch 30

`--watch` redraws every N seconds until you interrupt it. Nothing here writes
to either directory, so watching cannot disturb what it watches.
"""

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import ledger, stoprule


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _age(seconds: float) -> str:
    """A duration a human reads at a glance: 38s, 12m, 4h 07m, 2d 3h."""
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 90:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def _iso(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value)


def batches(run_dir: Path) -> dict:
    """Submitted, drained and still-in-flight batch handles, by route.

    A handle whose every cache key is already stored has landed even if no
    drained marker was written, which is the same test `drain_orphans` applies
    before it re-polls. Anything else is either in flight or an orphan waiting
    for the next invocation to harvest it — and either way it is paid for.
    """
    handles, drained = {}, set()
    for row in _rows(run_dir / "_batches.jsonl"):
        if row.get("kind") == "handle":
            handles[row.get("batch_id") or f"file:{row.get('input_file_id')}"] = row
        elif row.get("kind") == "drained":
            drained.add(row["batch_id"])
    cache = {}
    results = run_dir / "_results.jsonl"
    if results.exists():
        cache = {json.loads(line)["key"] for line in
                 results.read_text(encoding="utf-8").splitlines() if line.strip()}
    open_by_route: dict[str, int] = {}
    for key, row in handles.items():
        if row.get("batch_id") in drained:
            continue
        if not row.get("refresh_ids") and all(k in cache for k in row["keys"].values()):
            continue
        route = row.get("route", "unknown")
        open_by_route[route] = open_by_route.get(route, 0) + 1
    return {"submitted": len(handles), "drained": len(drained), "open": open_by_route}


def seed_snapshot(out_dir: Path, cheap: Path | None = None) -> dict:
    """Where seed authoring is, from what `mask_off.seedgen` leaves on disk.

    Authoring is a separate stage with a separate directory: `author` writes
    `scenarios/seeds/*.md` plus one `author_log.jsonl` record per taxonomy row,
    and `cheap` writes one audit record per seed. A failed row is logged and
    never retried, so counting rows against seeds is how you find the rows to
    re-author.
    """
    out_dir = Path(out_dir)
    seeds_dir = out_dir / "scenarios" / "seeds"
    log = _rows(out_dir / "author_log.jsonl")

    cheap_path = cheap or (out_dir.parent / f"{out_dir.name}_cheap.jsonl")
    audits = {r["seed_name"]: r.get("audit") for r in _rows(cheap_path) if "seed_name" in r}
    judged = [a for a in audits.values() if a]

    entries = ledger.usage_entries(
        [r["usage"] for r in log if r.get("usage")], stage="seedgen"
    ) if log else []
    return {
        "out_dir": out_dir,
        "exists": seeds_dir.exists() or bool(log),
        "seeds_on_disk": len(list(seeds_dir.glob("*.md"))) if seeds_dir.exists() else 0,
        "rows_attempted": len(log),
        "rows_failed": sum(1 for r in log if r.get("error")),
        "domains": sorted({r["domain"] for r in log if r.get("domain")}),
        "cheap_path": cheap_path if cheap_path.exists() else None,
        "audited": len(judged),
        "audit_passed": sum(1 for a in judged if a.get("verdict")),
        "cost": ledger.total(entries),
        "started": _iso(log[0]["ts"]) if log else None,
        "last": _iso(log[-1]["ts"]) if log else None,
    }


def render_seeds(snap: dict) -> Panel:
    if not snap["exists"]:
        return Panel(
            Text(f"no seed authoring under {snap['out_dir']}", style="yellow"),
            title="seeds", border_style="grey37",
        )
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold magenta", justify="right")
    table.add_column()

    rows, failed = snap["rows_attempted"], snap["rows_failed"]
    written = snap["seeds_on_disk"]
    table.add_row("seeds", f"{written} written to disk")
    detail = f"{rows} attempted"
    if failed:
        detail += f",  {failed} FAILED and not retried"
    if rows:
        detail += f"   {written / rows:.1f} seeds per row"
    table.add_row("rows", Text(detail, style="red" if failed else None))
    if snap["domains"]:
        table.add_row("domains", f"{len(snap['domains'])} covered")

    if snap["audited"]:
        passed = snap["audit_passed"]
        table.add_row("cheap screen", Text.assemble(
            f"{passed} / {snap['audited']} pass  ",
            _bar(passed, snap["audited"]),
            f"  {passed / snap['audited']:.0%}",
        ))
    else:
        # Absent is the normal production state, not a gap. Say so, or every
        # large run looks like it is missing a step it deliberately skipped.
        table.add_row("cheap screen", Text(
            "not run — pilot only, opt in with `seedgen screen --cheap`",
            style="dim"))

    table.add_row("cost", _money(snap["cost"]))
    if snap["started"] and snap["last"]:
        elapsed = (snap["last"] - snap["started"]).total_seconds()
        idle = (datetime.datetime.now(datetime.timezone.utc) - snap["last"]).total_seconds()
        table.add_row("clock", f"{_age(elapsed)} elapsed   "
                               f"last record {_age(idle)} ago")

    return Panel(Group(Text(snap["out_dir"].name, style="bold"), Text(""), table),
                 title="seeds", border_style="magenta")


def snapshot(run_dir: Path) -> dict:
    """Everything the display needs, as plain data. No rich, no I/O beyond reads."""
    run_dir = Path(run_dir)
    state = {}
    state_path = run_dir / "state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))

    log_path = run_dir / "run_log.jsonl"
    log = _rows(log_path)
    items = _rows(run_dir / "accepted.jsonl")
    cohorts = _rows(run_dir / "cohorts.jsonl")

    lock = run_dir / "_scale.pid"
    pid = int(lock.read_text().strip() or 0) if lock.exists() else 0
    alive = bool(pid and _alive(pid))

    # A live run must not have its stop reasons inferred: inference reads the
    # cap the log attests to, and on a running log the deepest wave reached is
    # only how far the run has got. Twenty seeds part way through wave 1 read
    # as `cap_exhausted 16` against an inferred cap of 1 while every one of
    # them was about to revise.
    replay = stoprule.replay(
        log, live=state.get("in_flight") or (), infer=not alive
    ) if log else {}
    entries = ledger.log_entries(log_path) if log_path.exists() else []
    # One definition of what a run has bought, shared with the cost ceiling:
    # the log, plus the cached requests of waves that have not tallied yet.
    committed = ledger.committed_total(run_dir)

    now = datetime.datetime.now(datetime.timezone.utc)
    started = _iso(log[0]["ts"]) if log else None
    last = _iso(log[-1]["ts"]) if log else None

    evals = sorted((run_dir / "eval").glob("cohort_*_eval.jsonl"))
    return {
        "run_dir": run_dir,
        "exists": run_dir.exists(),
        "pid": pid if alive else 0,
        "target": state.get("target"),
        "items": len(items),
        "cohort": state.get("cohort", 0),
        "in_flight": state.get("in_flight") or [],
        "run_yield": state.get("run_yield"),
        "seeds_consumed": len(state.get("consumed") or []),
        "cohorts": cohorts,
        "replay": replay,
        "cost": ledger.total(entries),
        "committed": committed,
        "cost_by_stage": ledger.by_stage(entries),
        "cost_by_route": ledger.by_route(entries),
        "started": started,
        "elapsed": (last - started).total_seconds() if started and last else 0,
        "idle": (now - last).total_seconds() if last else None,
        "batches": batches(run_dir),
        "eval_files": [p.name for p in evals],
        "eval_rows": sum(len(_rows(p)) for p in evals),
    }


def _money(dollars: float) -> str:
    """Seed authoring runs at fractions of a cent, Stage A at hundreds of
    dollars. Two decimals hide the first; four are noise on the second."""
    return f"${dollars:,.2f}" if dollars >= 1 else f"${dollars:.4f}"


def _bar(done: int, total: int | None, width: int = 30) -> Text:
    """A plain block bar. rich's ProgressBar wants a live display to size
    itself against; this is a string and renders the same everywhere, including
    into a pipe or a log file."""
    if not total:
        return Text("—")
    filled = min(width, round(width * done / total))
    return Text.assemble(
        ("█" * filled, "green"), ("░" * (width - filled), "grey37"),
    )


def render(snap: dict) -> Panel:
    if not snap["exists"]:
        return Panel(Text(f"no such run directory: {snap['run_dir']}", style="red"))

    replay, target, items = snap["replay"], snap["target"], snap["items"]
    live = (
        Text("running", style="bold green") if snap["pid"]
        else Text("not running", style="yellow")
    )
    if snap["pid"]:
        live.append(f" (pid {snap['pid']})", style="dim")

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", justify="right")
    table.add_column()

    if target:
        table.add_row("items", Text.assemble(
            f"{items} / {target}  ", _bar(items, target),
            f"  {items / target:.0%}" if target else "",
        ))
    else:
        table.add_row("items", str(items))

    cohort = f"checkpoint {snap['cohort']}"
    if snap["in_flight"]:
        cohort += f", {len(snap['in_flight'])} seeds in flight"
    if snap["run_yield"] is not None:
        cohort += f"   run yield {snap['run_yield']:.2f}"
    table.add_row("draw", f"{snap['seeds_consumed']} seeds drawn   {cohort}")

    if replay:
        reasons = "  ".join(f"{k} {v}" for k, v in sorted(replay["stop_reasons"].items()))
        table.add_row("waves", f"{replay['waves']} over {replay['seeds']} seeds   {reasons}")
        if snap["pid"]:
            table.add_row("", Text(
                "a live run reports only recorded outcomes; `running` means "
                "the seed is still revising", style="dim"))
        occupancy = replay.get("occupancy") or {}
        if occupancy.get("wave_occupancy") is not None:
            table.add_row("occupancy", f"{occupancy['wave_occupancy']:.0%} of the "
                                       f"seed-waves the run held slots open for")

    stages = "  ".join(f"{k} {_money(v)}" for k, v in sorted(snap["cost_by_stage"].items()))
    per_item = f"   {_money(snap['cost'] / items)}/item" if items else ""
    table.add_row("cost", f"{_money(snap['cost'])}{per_item}")
    if stages:
        table.add_row("", Text(stages, style="dim"))
    # The run log only gains a record when a WAVE tallies, so the line above is
    # $0.00 for the whole of a run's first wave while requests are landing and
    # being billed. Show what the cache already holds whenever it is ahead.
    if snap["committed"] > snap["cost"] + 0.005:
        table.add_row("", Text(
            f"{_money(snap['committed'])} already bought "
            f"(requests landed, waves not yet tallied)", style="yellow"))

    batch = snap["batches"]
    open_now = sum(batch["open"].values())
    detail = ", ".join(f"{k} {v}" for k, v in sorted(batch["open"].items())) or "none"
    style = "bold yellow" if open_now else "dim"
    table.add_row("batches", Text(f"{open_now} in flight ({detail})   "
                                  f"{batch['submitted']} submitted, "
                                  f"{batch['drained']} drained", style=style))

    if snap["started"]:
        idle = _age(snap["idle"]) if snap["idle"] is not None else "—"
        table.add_row("clock", f"{_age(snap['elapsed'])} elapsed   "
                               f"last record {idle} ago")

    if snap["eval_files"]:
        table.add_row("Stage B", f"{snap['eval_rows']} cells across "
                                 f"{len(snap['eval_files'])} cohorts")
    else:
        table.add_row("Stage B", Text("not started", style="dim"))

    name = snap["run_dir"].name or str(snap["run_dir"])
    header = Text.assemble(Text(name, style="bold"), "   ", live)
    return Panel(Group(header, Text(""), table), title="MASK-OFF", border_style="cyan")


def screen(run_dir: Path | None, seeds_dir: Path | None) -> Group:
    """Whichever panels the caller asked for, in pipeline order."""
    panels = []
    if seeds_dir is not None:
        panels.append(render_seeds(seed_snapshot(seeds_dir)))
    if run_dir is not None:
        panels.append(render(snapshot(run_dir)))
    return Group(*panels)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Print where a run is. Read-only; safe against a live run.")
    parser.add_argument("run_dir", type=Path, nargs="?", default=None,
                        help="a scale run directory (Stage A and Stage B)")
    parser.add_argument("--seeds", type=Path, default=None, metavar="DIR",
                        help="a seedgen output directory (the authoring stage)")
    parser.add_argument("--watch", type=float, default=None, metavar="SECONDS",
                        help="redraw every SECONDS until interrupted")
    args = parser.parse_args(argv)
    if args.run_dir is None and args.seeds is None:
        parser.error("give a run directory, --seeds DIR, or both")

    console = Console()
    if args.watch is None:
        console.print(screen(args.run_dir, args.seeds))
        return
    try:
        while True:
            console.clear()
            console.print(screen(args.run_dir, args.seeds))
            console.print(Text(f"watching every {args.watch:g}s — ctrl-c to stop",
                               style="dim"))
            time.sleep(args.watch)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
