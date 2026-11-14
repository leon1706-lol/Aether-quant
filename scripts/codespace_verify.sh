#!/usr/bin/env bash
# Every CI job, on a Codespace, against the local working tree in a clean checkout: what the owner's push would meet, before the push. Each stage records its own result and is skipped on a
# rerun, so a VM reboot costs one stage. Run detached and poll /tmp/aq_verify/status (scripts/codespace_keepalive.sh holds the session). Needs /tmp/aq_verify/worktree.patch and untracked.tgz.
#   setsid nohup bash scripts/codespace_verify.sh > /tmp/aq_verify/run.log 2>&1 < /dev/null &
# No Lean run and no Docker: those belong on the DinD Codespace (scripts/codespace_lean_run.ps1, scripts/codespace_engine_check.sh).
set -u
STATE=/tmp/aq_verify
CLEAN=/tmp/aq_clean
REPO=/workspaces/Aether-quant
STATUS="${STATE}/status"
mkdir -p "${STATE}"
# pip's console scripts (ruff, aq, av, pip-audit) land in the user base, which a detached shell doesn't have on PATH.
PATH="$(python3 -m site --user-base)/bin:${HOME}/.local/bin:${PATH}"
export PATH
stage() {
  local name="$1"; shift
  if grep -q "^PASS ${name}\$" "${STATUS}" 2>/dev/null; then return 0; fi
  sed -i "/^FAIL ${name}\$/d" "${STATUS}" 2>/dev/null
  echo "RUN ${name} $(date -u +%T)" >> "${STATUS}"
  if ( "$@" ) > "${STATE}/${name}.log" 2>&1; then echo "PASS ${name}" >> "${STATUS}"; else echo "FAIL ${name}" >> "${STATUS}"; fi
}

prepare() {
  cd "${REPO}" || return 1
  git fetch origin main || return 1
  rm -rf "${CLEAN}"
  git worktree prune
  git worktree add --detach "${CLEAN}" FETCH_HEAD || return 1
  cd "${CLEAN}" || return 1
  git apply --whitespace=nowarn "${STATE}/worktree.patch" || return 1
  tar -xzf "${STATE}/untracked.tgz" || return 1
  git log -1 --oneline
  git status --short | wc -l
}

deps() {
  cd "${CLEAN}" || return 1
  python3 -m pip install --quiet --upgrade pip
  python3 -m pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu
  python3 -m pip install --quiet -r requirements/requirements.txt -r requirements/requirements-dev.txt pytest-cov pytest-xdist build pip-audit
  python3 -m pip install --quiet -e .
  python3 -m pip show aether-vault | head -2
  python3 --version
}

suite() { cd "${CLEAN}" && python3 -m pytest -m "not lean_backtest" -ra -n 3 --cov --cov-report=term-missing --cov-report=xml --cov-fail-under=80; }
lint() { cd "${CLEAN}" && python3 -m pip install --quiet "ruff==0.16.4" && ruff check . && python3 -m py_compile main.py; }
guards() {
  cd "${CLEAN}" && python3 -m pytest -q -p no:cacheprovider tests/test_cli_help_surface.py tests/test_ci_workflows.py tests/test_dockerignore_secrets.py tests/test_lean_runtime_imports.py \
    tests/test_packaging_modules.py tests/test_docs_links.py tests/test_docs_facts.py tests/test_aether_quant_coverage.py tests/test_v550_parity_fixes.py "tests/test_aq_cli.py::test_subsystem_test_files_maps_every_real_test_file_to_exactly_one_bucket"
}
bucket() { cd "${CLEAN}" && python3 aq_cli.py test "--$1"; }
actionlint_job() {
  cd "${CLEAN}" || return 1
  curl -sSL -o "${STATE}/actionlint.tar.gz" https://github.com/rhysd/actionlint/releases/download/v1.7.7/actionlint_1.7.7_linux_amd64.tar.gz || return 1
  tar -xzf "${STATE}/actionlint.tar.gz" -C "${STATE}" actionlint || return 1
  "${STATE}/actionlint" -no-color -verbose
}
webui() {
  command -v node > /dev/null || {
    curl -sSL -o "${STATE}/node.tar.xz" https://nodejs.org/dist/v20.19.5/node-v20.19.5-linux-x64.tar.xz && tar -xJf "${STATE}/node.tar.xz" -C "${STATE}" || return 1
    export PATH="${STATE}/node-v20.19.5-linux-x64/bin:${PATH}"
  }
  cd "${CLEAN}/webui" || return 1
  node --version && npm ci && npx tsc -b && npx oxlint && npx vitest run --pool=threads && npm run build
}
cli_smoke() {
  cd "${CLEAN}" || return 1
  aq --help > /dev/null && aq evaluate --help > /dev/null && aq cycle --help > /dev/null && aq config get phase1.universe.name && aq secrets-check
}
wheel() {
  cd "${CLEAN}" || return 1
  git -C "${CLEAN}" fetch --tags --quiet origin || true
  rm -rf dist "${STATE}/wheelenv"
  python3 -m build --wheel || return 1
  python3 -m venv --system-site-packages "${STATE}/wheelenv" || return 1
  "${STATE}/wheelenv/bin/pip" install --quiet --no-deps --force-reinstall dist/*.whl || return 1
  rm -rf dist build
  cd "${STATE}" && "${STATE}/wheelenv/bin/python" "${CLEAN}/scripts/wheel_smoke.py"
}
compat() {
  command -v python3.10 > /dev/null && { cd "${CLEAN}" && python3.10 -m compileall -q -x '(^|/)(\.git|\.venv|venv|node_modules|backtests|webui|Aether-quant-Obsidian-Vault|build|dist|\.matplotlib_cache)(/|$)' .; return $?; }
  python3 -m pip install --quiet vermin || return 1
  cd "${CLEAN}" && vermin -t=3.10- --no-tips --violations -q aether_quant evaluation portfolio features scripts/cycle_daily.py scripts/cycle_decide.py scripts/cycle_lean.py scripts/cycle_retrain.py aq_cli.py train_cross_sectional.py
}
parity() {
  cd "${CLEAN}" && python3 -m pytest -q -p no:cacheprovider tests/test_backtest_audit.py tests/test_live_parity.py tests/test_volatility_threshold_calibration.py tests/test_legacy_sleeve.py \
    tests/test_performance_probe.py tests/test_rank_book_simulator.py tests/test_feature_parity.py && python3 scripts/feature_parity_audit.py --synthetic-only
}
gitleaks_job() {
  cd "${CLEAN}" || return 1
  curl -sSL -o "${STATE}/gitleaks.tar.gz" https://github.com/gitleaks/gitleaks/releases/download/v8.18.4/gitleaks_8.18.4_linux_x64.tar.gz || return 1
  tar -xzf "${STATE}/gitleaks.tar.gz" -C "${STATE}" gitleaks || return 1
  "${STATE}/gitleaks" detect --source . --no-git --no-banner --redact --exit-code 1 --config .gitleaks.toml
}
audit() { cd "${CLEAN}" && pip-audit --requirement requirements/requirements.txt --desc && pip-audit --requirement requirements/requirements-dev.txt --desc; }
hadolint_job() {
  cd "${CLEAN}" || return 1
  curl -sSL -o "${STATE}/hadolint" https://github.com/hadolint/hadolint/releases/download/v2.12.0/hadolint-Linux-x86_64 && chmod +x "${STATE}/hadolint" && "${STATE}/hadolint" --failure-threshold error Dockerfile Dockerfile.lean
}
vault() {
  # AetherVault for real: the pinned CLI, and the contract tests that run it, in the tree with this project's data and in the clean one.
  cd "${CLEAN}" || return 1
  command -v av || return 1
  av --version
  # To a file, not a pipe: the real `av` leaves a daemon holding its stdout, and a pipe would never close.
  AQ_AV_BINARY="$(command -v av)" python3 -m pytest -q -p no:cacheprovider -rs tests/test_vault_contract.py tests/test_vault_client.py tests/test_vault_commands.py tests/test_vault_record.py > "${STATE}/vault_tests.log" 2>&1
  tail -n 3 "${STATE}/vault_tests.log"
  # A skipped contract test proves nothing about the real CLI, so it fails this stage.
  ! grep -q "real av not available" "${STATE}/vault_tests.log" || return 1
  ! grep -qE "[0-9]+ failed" "${STATE}/vault_tests.log" || return 1
  grep -qE "[0-9]+ passed" "${STATE}/vault_tests.log" || return 1
  # The pinned version against what config.json demands, in a real repository, so "not an av repo" can't pass for "not installed".
  av init > /dev/null 2>&1
  python3 -c "
import json, pathlib, sys
from retraining.vault_client import vault_preflight
report = vault_preflight(json.loads(pathlib.Path('config.json').read_text(encoding='utf-8'))['phase_v2']['retraining']['vault'])
print(json.dumps(report))
sys.exit(0 if report['ok'] else 1)
"
}
real_tree() {
  # The same suite in the tree that holds the data, where the tests that skip in a clean checkout run. Its bucket lets it use the Codespace's cores.
  cd "${REPO}" && timeout 3300 python3 -m pytest -m "not lean_backtest" -q -n 3 -p no:cacheprovider
}

stage prepare prepare
stage deps deps
stage suite suite
stage lint lint
stage guards guards
for name in cli audit risk portfolio features data-pipeline webui ml retraining notifications storage live evaluation formal meta; do
  stage "bucket_${name}" bucket "${name}"
done
stage actionlint actionlint_job
stage webui webui
stage cli_smoke cli_smoke
stage wheel wheel
stage compat compat
stage parity parity
stage gitleaks gitleaks_job
stage pip_audit audit
stage hadolint hadolint_job
stage vault vault
stage real_tree real_tree
echo "ALL_DONE $(date -u +%T)" >> "${STATUS}"
