"""`aq init` (V6.6.10): a new signal project from the template shipped in the wheel (`aether_quant/_templates/project/`).

The template holds a starter signal, its tests (shape and no look-ahead), a pipeline file with its gate, a README and a GitHub
workflow that runs the tests and the pipeline on free runners. `{{name}}` and `{{version}}` are filled in when it is copied, and a
`.tmpl` suffix is dropped.
"""

from __future__ import annotations

from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "aether_quant" / "_templates" / "project"
RENAMES = {"gitignore": ".gitignore", "workflow.yml": ".github/workflows/pipeline.yml"}


def template_files(template: Path = TEMPLATE) -> dict[str, Path]:
    """Each template file by the path it gets in the new project."""
    out = {}
    for path in sorted(template.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            relative = path.relative_to(template).as_posix()
            # `.tmpl`: the template's Python stays out of this repo's own lint, coverage and library gate until it is copied
            out[RENAMES.get(relative, relative.removesuffix(".tmpl"))] = path
    return out


def render(text: str, *, name: str, version: str) -> str:
    return text.replace("{{name}}", name).replace("{{version}}", version)


def create_project(target: Path, *, name: str | None = None, version: str = "0.0.0", template: Path = TEMPLATE) -> list[str]:
    """Writes the template into `target` (created if missing) and returns the files written. Refuses a folder that already holds
    anything, so an existing project is never overwritten."""
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"{target} is not empty: aq init only writes into a new or empty folder")
    name = name or target.resolve().name
    written = []
    for relative, source in template_files(template).items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render(source.read_text(encoding="utf-8"), name=name, version=version), encoding="utf-8", newline="\n")
        written.append(relative)
    return written
