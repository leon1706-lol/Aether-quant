"""Pure Aether-Vault (`av`) command builder (Phase V2-17).

Builds argv lists only - no subprocess execution here, see
retraining/vault_client.py for that. Aether-Vault is a separate sibling
tool, invoked purely as an external `av` CLI subprocess; its internals are
out of scope and this repo never reads/imports anything from it.
"""

from __future__ import annotations


def build_av_add_command(paths: list[str], av_binary: str = "av") -> list[str]:
    return [av_binary, "add", *paths]


def build_av_commit_command(
    message: str,
    tag: str,
    metrics: dict[str, float],
    av_binary: str = "av",
) -> list[str]:
    cmd = [av_binary, "commit", "-m", message]
    if tag:
        cmd += ["--tag", tag]
    for key, value in metrics.items():
        cmd += ["--metric", f"{key}={value}"]
    return cmd


def build_av_push_command(av_binary: str = "av") -> list[str]:
    return [av_binary, "push"]


def build_commit_plan(version_id: str, add_paths: list[str], metrics: dict[str, float], config: dict) -> dict:
    """Assembles the full add -> commit -> push argv plan for one candidate.

    config = phase_v2.retraining.vault block. `push` defaults to True per
    that config's own default; set config["push"]=False to skip the push
    step (e.g. commit-only, offline dev).
    """
    av_binary = config.get("av_binary", "av")
    message_template = config.get("commit_message_template", "candidate model {version_id}")
    tag = config.get("tag", "candidate")

    plan = {
        "add": build_av_add_command(add_paths, av_binary=av_binary),
        "commit": build_av_commit_command(
            message_template.format(version_id=version_id), tag, metrics, av_binary=av_binary
        ),
        "push": build_av_push_command(av_binary=av_binary) if config.get("push", True) else None,
    }
    return plan
