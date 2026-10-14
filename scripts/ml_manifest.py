"""SHA-256 manifest of the INSTALLED model files (ml/ top level and ml/expert_models), identical output on every machine.

    python scripts/ml_manifest.py [--ml-dir ml]   ->  "<sha256>  <relative path>" per file, sorted

Compare the local and the Codespace manifest with `diff` before trusting an evaluation that ran on the other side;
datasets, versions, backups and evaluation reports are not installed models and are left out.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

INSTALLED_SUFFIXES = {".json", ".pt", ".pth", ".npz", ".npy", ".onnx", ".bin"}
SKIP_TOP_LEVEL = {"datasets", "versions", "evaluation", "expert_datasets", "cache"}


def installed_files(ml_dir: Path) -> list[Path]:
    files = [path for path in ml_dir.iterdir() if path.is_file() and path.suffix in INSTALLED_SUFFIXES]
    experts = ml_dir / "expert_models"
    if experts.is_dir():
        files.extend(path for path in experts.rglob("*") if path.is_file() and path.suffix in INSTALLED_SUFFIXES)
    return sorted(files, key=lambda path: path.relative_to(ml_dir).as_posix())


def manifest_lines(ml_dir: Path) -> list[str]:
    lines = []
    for path in installed_files(ml_dir):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(ml_dir).as_posix()}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ml-dir", default=str(Path(__file__).resolve().parents[1] / "ml"))
    print("\n".join(manifest_lines(Path(parser.parse_args().ml_dir))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
