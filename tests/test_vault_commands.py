"""Tests for retraining.vault_commands — V2-17.

Conventions: no test classes, module-level helpers, pure argv-builder
functions tested with plain assertions (no subprocess involved).
"""

from retraining.vault_commands import (
    build_av_add_command,
    build_av_commit_command,
    build_av_push_command,
    build_commit_plan,
)


def test_build_av_add_command():
    argv = build_av_add_command(["train.py", "ml/versions/abc/"])

    assert argv == ["av", "add", "train.py", "ml/versions/abc/"]


def test_build_av_commit_command_formats_tag_and_metrics():
    argv = build_av_commit_command("candidate model abc", "candidate", {"sharpe": 1.5, "drawdown": -0.1})

    assert argv[:4] == ["av", "commit", "-m", "candidate model abc"]
    assert "--tag" in argv and "candidate" in argv
    assert "--metric" in argv
    assert "sharpe=1.5" in argv
    assert "drawdown=-0.1" in argv


def test_build_av_commit_command_omits_tag_when_empty():
    argv = build_av_commit_command("msg", "", {})

    assert "--tag" not in argv


def test_build_av_push_command():
    assert build_av_push_command() == ["av", "push"]


def test_build_av_push_command_custom_binary():
    assert build_av_push_command(av_binary="/usr/local/bin/av") == ["/usr/local/bin/av", "push"]


def test_build_commit_plan_assembles_all_three_steps():
    config = {
        "av_binary": "av",
        "commit_message_template": "candidate model {version_id}",
        "tag": "candidate",
        "push": True,
    }

    plan = build_commit_plan("abc-123", ["train.py"], {"sharpe": 1.0}, config)

    assert plan["add"] == ["av", "add", "train.py"]
    assert plan["commit"][3] == "candidate model abc-123"
    assert plan["push"] == ["av", "push"]


def test_build_commit_plan_skips_push_when_configured_off():
    config = {"push": False}

    plan = build_commit_plan("abc-123", ["train.py"], {}, config)

    assert plan["push"] is None
