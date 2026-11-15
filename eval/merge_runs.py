"""Merge several run_eval.py output folders into one eval/results.json and eval/RESULTS.md.

Used on Nov 15 because the metrics run started on the 12 files that were ready while the last two
normal calls were still being voiced; the remaining 4 files ran afterwards. Nothing is recomputed
from scratch: the per-call results are concatenated and the same aggregate() and write_markdown()
from run_eval.py produce the table.

    .\\.venv\\Scripts\\python.exe -m eval.merge_runs eval\\run_part1 eval\\run_part2
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from eval.run_eval import HERE, aggregate, write_markdown


def main(folders: list[str]) -> int:
    runs = [json.loads((Path(f) / "results.json").read_text(encoding="utf-8")) for f in folders]
    calls = [c for r in runs for c in r["calls"]]
    keys = [(c["id"], c["variant"]) for c in calls]
    if len(keys) != len(set(keys)):
        print("the runs overlap: a call appears twice")
        return 1
    if any(r["meta"].get("mock") for r in runs):
        print("one of the runs was against the mock; refusing to merge")
        return 1
    meta = dict(runs[0]["meta"])
    meta["started_ist"] = min(r["meta"]["started_ist"] for r in runs)
    meta["finished_ist"] = max(r["meta"]["finished_ist"] for r in runs)
    meta["merged_from"] = [str(Path(f)) for f in folders]
    meta["health"] = runs[-1]["meta"]["health"]
    agg = aggregate(calls)
    (HERE / "results.json").write_text(json.dumps({"meta": meta, "aggregate": agg, "calls": calls},
                                                  ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(HERE / "RESULTS.md", meta, calls, agg)
    print(json.dumps(agg, indent=2))
    print(f"merged {len(calls)} calls into {HERE / 'results.json'} and {HERE / 'RESULTS.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
