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
