"""CLI: render a gitignored `lean.live.json` from `.env.live` / AETHER_* env vars.

Thin wrapper over execution/lean_config_render.py (the actual logic + tests
live there). Prints only which FIELDS were filled, never the secret values.

    python -m scripts.render_lean_credentials
    python -m scripts.render_lean_credentials --base lean.json --out lean.live.json --env-file .env.live

`aq render-lean-config` calls the same code path - see aq_cli.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from execution.lean_config_render import build_render_environment, write_rendered_config

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=str(REPO_ROOT / "lean.json"),
                        help="Empty tracked Lean template to render from (default: lean.json)")
    parser.add_argument("--out", default=str(REPO_ROOT / "lean.live.json"),
                        help="Rendered, secret-bearing output (gitignored; default: lean.live.json)")
    parser.add_argument("--env-file", default=str(REPO_ROOT / ".env.live"),
                        help="`.env`-style file with AETHER_* secrets (default: .env.live)")
    args = parser.parse_args(argv)

    env = build_render_environment(env_file=args.env_file)
    filled = write_rendered_config(args.base, args.out, env)

    if filled:
        print(f"Rendered {args.out} with {len(filled)} field(s): {', '.join(filled)}")
    else:
        print(
            f"Rendered {args.out}, but NO secret fields were populated - "
            f"check that {args.env_file} exists and its AETHER_* values are set."
        )
    print("Point Lean at it with: --lean-config " + args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
