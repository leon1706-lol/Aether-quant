# .devcontainer

Codespaces and Dev Container definitions. See [`development/infrastructure.md`](../development/infrastructure.md).

- **`devcontainer.json`:** the training Codespace. Python 3.11 with sshd, CPU PyTorch and both requirements files. Create it on 4 cores / 16 GB (`-m standardLinux32gb`), with `--devcontainer-path .devcontainer/devcontainer.json`, because the repo has two definitions.
- **`dind-v1-test/`:** Lean backtests in a temporary 4-core Codespace. Pinned to `python:3.11-bookworm` (the Docker-in-Docker feature doesn't support Debian trixie). Move Docker's data root to the large local disk before building the 20 GB image: `/etc/docker/daemon.json` with `{"data-root": "/tmp/docker-data", "dns": ["168.63.129.16"]}`, then restart `dockerd`.
