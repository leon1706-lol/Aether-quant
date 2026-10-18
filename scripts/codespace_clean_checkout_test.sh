#!/usr/bin/env bash
# CI's view of the repository on the Codespace (V6.3.0): the dev PC cannot hold the suite, so
# scripts/clean_checkout_test.ps1's check runs here. The tarball holds exactly the files a commit would contain
# (`git ls-files --cached --others --exclude-standard` on the PC): no gitignored artifact (ml/, data/, backtests/).
#   bash scripts/codespace_clean_checkout_test.sh /tmp/aq_clean.tgz [log path, default /tmp/aq_clean_test.log]
set -u
TARBALL="${1:?tarball of the files a commit would hold}"
LOG="${2:-/tmp/aq_clean_test.log}"
WORK=/tmp/aq-clean-checkout
rm -rf "${WORK}" && mkdir -p "${WORK}"
tar -xzf "${TARBALL}" -C "${WORK}"
cd "${WORK}"
PYTHONPATH="${WORK}" python -m pytest tests -m "not lean_backtest" -ra -q -p no:cacheprovider > "${LOG}" 2>&1
echo "clean-checkout pytest exit code: $?" >> "${LOG}"
