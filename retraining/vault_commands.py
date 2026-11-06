"""Pure Aether-Vault (`av`) command builder (Phase V2-17).

Builds argv lists only - no subprocess execution here, see
retraining/vault_client.py for that. Aether-Vault is a separate sibling
tool, invoked purely as an external `av` CLI subprocess. Commit, push and
restore ask for its versioned JSON envelope (docs/for-agents.md in that repo),
so results are read from a contract rather than from human text.
"""

from __future__ import annotations


def build_av_add_command(paths: list[str], av_binary: str = "av") -> list[str]:
    return [av_binary, "add", *paths]


def build_av_commit_command(
    message: str,
    tag: str,
    metrics: dict[str, float],
    av_binary: str = "av",
    *,
    no_upload: bool = False,
) -> list[str]:
    cmd = [av_binary, "--output", "json", "commit", "-m", message]
    if tag:
        cmd += ["--tag", tag]
    for key, value in metrics.items():
        cmd += ["--metric", f"{key}={value}"]
    if no_upload:
        cmd.append("--no-upload")
    return cmd


def build_av_push_command(av_binary: str = "av") -> list[str]:
    return [av_binary, "--output", "json", "push"]


def build_av_status_command(av_binary: str = "av") -> list[str]:
    return [av_binary, "--output", "json", "status"]


def build_av_head_command(av_binary: str = "av") -> list[str]:
    return [av_binary, "--output", "json", "log", "--limit", "1"]


def build_av_restore_command(commit_hash: str, paths: list[str], av_binary: str = "av") -> list[str]:
    """Restores only `paths`: HEAD and every other file stay as they are."""
    return [av_binary, "--output", "json", "restore", "--source", commit_hash, *paths]


def build_commit_plan(version_id: str, add_paths: list[str], metrics: dict[str, float], config: dict) -> dict:
    """Assembles the full add -> commit -> push argv plan for one candidate.

    config = phase_v2.retraining.vault block. `push` defaults to True per
    that config's own default; set config["push"]=False to skip the push
    step (e.g. commit-only, offline dev), which also keeps the commit itself
    from attempting an upload.
    """
    av_binary = config.get("av_binary", "av")
    message_template = config.get("commit_message_template", "candidate model {version_id}")
    tag = config.get("tag", "candidate")
    push = config.get("push", True)
    paths = [*add_paths, *config.get("extra_add_paths", [])]

    plan = {
        "add": build_av_add_command(paths, av_binary=av_binary),
        "commit": build_av_commit_command(
            message_template.format(version_id=version_id), tag, metrics, av_binary=av_binary, no_upload=not push
        ),
        "push": build_av_push_command(av_binary=av_binary) if push else None,
    }
    return plan
