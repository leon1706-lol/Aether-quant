"""Per-call cost of the V6.4.3 changes to the verified hot-path functions, against the committed versions (git HEAD):
`apply_book_neutrality`, `cap_target_weight`, `build_dynamic_position_sizing`, `trailing_drawdown`. Outputs must be
bit-identical on finite inputs; the guards may only add negligible time.

    python scripts/v643_microbench.py [--calls 20000] [--out ml/evaluation/v643/microbench.json]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import subprocess
import sys
import tempfile
import timeit
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

FILES = {"book_neutrality": "portfolio/book_neutrality.py", "risk_controls": "risk_controls.py",
         "position_sizing": "risk/position_sizing.py", "sleeve_guard": "portfolio/sleeve_guard.py"}


def _committed_module(name: str, relative: str, tmp: Path):
    source = subprocess.run(["git", "show", f"HEAD:{relative}"], cwd=ROOT_DIR, capture_output=True, text=True, check=True).stdout
    package = Path(relative).parent.as_posix().replace("/", ".")
    if package and package != ".":
        source = source.replace("from .", f"from {package}.")  # loaded outside its package
    path = tmp / f"committed_{name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"committed_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--calls", type=int, default=20000)
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v643" / "microbench.json"))
    args = parser.parse_args()
    import portfolio.book_neutrality as new_neutrality
    import portfolio.sleeve_guard as new_sleeve
    import risk.position_sizing as new_sizing
    import risk_controls as new_risk

    rng = random.Random(7)
    books = []
    for _ in range(200):
        n = rng.randint(4, 14)
        books.append(({f"S{i}": rng.uniform(-0.25, 0.25) for i in range(n)}, {f"S{i}": f"X{rng.randint(0, 3)}" for i in range(n)}))
    kwargs = dict(dollar_neutral=True, sector_neutral=True, gross_exposure_cap=1.0, max_weight_per_name=0.12, sector_max_net_weight=0.15)
    targets = [(rng.uniform(-0.5, 0.5), rng.uniform(0, 1), 1.0) for _ in range(200)]
    pnl = [[rng.uniform(-1, 1) for _ in range(60)] for _ in range(50)]
    report: dict = {}
    with tempfile.TemporaryDirectory() as tmp:
        old = {name: _committed_module(name, relative, Path(tmp)) for name, relative in FILES.items()}
        cases = {
            "apply_book_neutrality": (lambda m: [m.apply_book_neutrality(w, sector_by_symbol=s, **kwargs)[0] for w, s in books],
                                      old["book_neutrality"], new_neutrality),
            "cap_target_weight": (lambda m: [m.cap_target_weight(*t) for t in targets], old["risk_controls"], new_risk),
            "build_dynamic_position_sizing": (lambda m: [m.build_dynamic_position_sizing(t[0], t[1], 0.02, 0.12).target_weight
                                                         for t in targets], old["position_sizing"], new_sizing),
            "trailing_drawdown": (lambda m: [m.trailing_drawdown(series, 30) for series in pnl], old["sleeve_guard"], new_sleeve),
        }
        for name, (call, before, after) in cases.items():
            identical = call(before) == call(after)
            repeats = max(1, args.calls // 200)
            t_old = min(timeit.repeat(lambda: call(before), number=repeats, repeat=3)) / (repeats * 200) * 1e6
            t_new = min(timeit.repeat(lambda: call(after), number=repeats, repeat=3)) / (repeats * 200) * 1e6
            report[name] = {"identical_outputs": identical, "committed_us_per_call": round(t_old, 3), "v643_us_per_call": round(t_new, 3),
                            "change_pct": round((t_new / t_old - 1) * 100, 1) if t_old else None}
            print(name, report[name], flush=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0 if all(row["identical_outputs"] for row in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
