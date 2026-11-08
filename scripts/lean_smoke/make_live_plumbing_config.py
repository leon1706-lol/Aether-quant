"""The two configs for `live_plumbing.sh` (V6.6.4, B6): Lean's launcher config for main.py under `live-paper` with a FakeDataQueue, and a project config trimmed to a few
crypto names so the algorithm starts quickly. Both are written outside the repo; lean.json and config.json are read, never changed.

    python scripts/lean_smoke/make_live_plumbing_config.py --lean-json lean.json --out launcher.json --project-config <project>/config.json
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

FAKE_QUEUE = "QuantConnect.Lean.Engine.DataFeeds.Queues.FakeDataQueue"


def launcher_config(lean: dict) -> dict:
    base = {key: copy.deepcopy(value) for key, value in lean.items() if key != "environments"}
    environments = lean["environments"]
    live = copy.deepcopy(environments["live-paper"])
    live["data-queue-handler"] = [FAKE_QUEUE]
    base.update(live)
    base.update({
        "environment": "live-paper-fake",
        "algorithm-type-name": "AetherQuantAlgorithm",
        "algorithm-language": "Python",
        "algorithm-location": "/LeanCLI/main.py",
        "data-folder": "/Lean/Data",
        "results-destination-folder": "/Results",
        "debugging": False,
        "live-mode": True,
        "python-additional-paths": ["/LeanCLI"],
        "parameters": {},
    })
    base["environments"] = {"live-paper-fake": live}
    return base


def project_config(config: dict, keep: tuple[str, ...] = ("BTCUSD", "ETHUSD", "SOLUSD", "SPY", "TLT")) -> dict:
    config = copy.deepcopy(config)
    assets = [asset for asset in config["phase1"]["universe"]["assets"] if asset["ticker"] in keep]
    config["phase1"]["universe"]["assets"] = assets
    runtime = config.setdefault("runtime", {})
    runtime["mode"] = "paper"
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lean-json", default="lean.json")
    parser.add_argument("--out", required=True)
    parser.add_argument("--project-config", required=True, help="the copy of config.json inside the temp project; rewritten in place")
    args = parser.parse_args()
    lean = json.loads(Path(args.lean_json).read_text(encoding="utf-8"))
    Path(args.out).write_text(json.dumps(launcher_config(lean), indent=1), encoding="utf-8", newline="\n")
    project = Path(args.project_config)
    project.write_text(json.dumps(project_config(json.loads(project.read_text(encoding="utf-8"))), indent=1), encoding="utf-8", newline="\n")
    print(f"wrote {args.out} and trimmed {args.project_config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
