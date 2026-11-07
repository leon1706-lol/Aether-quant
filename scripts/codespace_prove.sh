#!/usr/bin/env bash
# The Lean 4 proofs and their differential cases, on a Codespace: Mathlib needs more memory than the dev PC has. Installs elan if absent, takes Mathlib from its cache, builds every module and
# regenerates aether_quant/_formal_cases/. Run detached; poll /tmp/aq_prove/status.
set -u
STATE=/tmp/aq_prove
mkdir -p "${STATE}"
STATUS="${STATE}/status"
mark() { echo "$(date -u +%FT%TZ) $1" >> "${STATUS}"; }
cd /workspaces/Aether-quant || exit 1
export PATH="${HOME}/.elan/bin:${PATH}"
mark PROVE_START
if ! command -v lake > /dev/null; then
  curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -o "${STATE}/elan-init.sh" && bash "${STATE}/elan-init.sh" -y --default-toolchain none > "${STATE}/elan.log" 2>&1
  mark "ELAN exit $?"
fi
cd formal || exit 1
# The push carries a Windows checkout of the packages with no built files; a fresh fetch follows lake-manifest.json and takes Mathlib's built files from its cache.
rm -rf .lake
lake exe cache get > "${STATE}/cache.log" 2>&1
mark "CACHE exit $?"
cd .. || exit 1
python3 aq_cli.py prove --check-sorry > "${STATE}/sorry.log" 2>&1
mark "SORRY exit $?"
python3 aq_cli.py prove --regen-cases > "${STATE}/prove.log" 2>&1
mark "PROVE exit $?"
mark PROVE_DONE
