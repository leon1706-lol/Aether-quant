# .devcontainer

GitHub Codespaces / VS Code Dev Container definition for Aether Quant
(`devcontainer.json`), plus a `dind-v1-test/` variant used to test
Docker-in-Docker setups.

The container is the `mcr.microsoft.com/devcontainers/python:3.11` image with
an sshd feature (Codespaces training access) and a post-create command that
installs the CPU PyTorch build plus both requirements files. This is the
environment behind this project's own "train in the cloud" convention — see
[`RUNBOOK.md`](../RUNBOOK.md) and
[`development/infrastructure.md`](../development/infrastructure.md).

`dind-v1-test/` (V6.2.0) runs Lean backtests in a 4-core / 16 GB Codespace: its base image is pinned to
`python:3.11-bookworm` (the Docker-in-Docker feature does not support Debian trixie, which `python:3.11` now
resolves to), and Docker's data root must move to the machine's large local disk (`/tmp`, 118 GB) before
building the ~20 GB Lean image: `/etc/docker/daemon.json` `{"data-root": "/tmp/docker-data", "dns": ["168.63.129.16"]}`
and a `dockerd` restart (see `development/infrastructure.md`).
