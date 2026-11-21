"""The model lab from the library: a lab folder, a dataset in the production layout, a linear model trained as counted trials,
then judged out of sample (a cost-aware book at the lab's N), compared with a momentum baseline, explained and exported to the
`aq models` format. No torch, no network: the bundled sample and the `linear` template. `aq lab` runs the same steps as commands
(docs/guide/model-lab.md); with torch, `--template multitask` trains the project's own network the same way.

    python examples/aether_quant_lab.py
"""

from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aether_quant import lab, samples


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "mylab"
        lab.init_lab(folder)
        dataset = lab.build_dataset(samples.load_sample_prices(), features="core", targets=(5, 20))
        dataset.to_csv(folder / "data" / "dataset.csv", index=False)
        print("dataset rows by split: " + ", ".join(f"{split} {count}" for split, count in dataset.groupby("split").size().items()))
        lab.new_model(folder, "ridge", "linear")
        record = lab.train_run(folder, "ridge", seeds=[1, 2], log=lambda line: None)
        print(f"run {record['id']}: out-of-sample IC {record['metrics']['oof_ic_mean']:.4f}, N {record['trials_n']}")
        run = lab.find_run(folder, "latest")
        report = lab.evaluate_run(run, lab_dir=folder, book=True)
        print(lab.render_eval(report))
        print(lab.render_compare(lab.compare_runs([run], baseline="momentum_20")))
        result = lab.export_run(run, folder / "ridge.zip", card=lab.model_card(run, report))
        print("exported " + ", ".join(sorted(zipfile.ZipFile(result["zip"]).namelist())))


if __name__ == "__main__":
    main()
