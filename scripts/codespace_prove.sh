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
fail=0
python3 aq_cli.py prove --check-sorry > "${STATE}/sorry.log" 2>&1
code=$?; mark "SORRY exit ${code}"; [ "${code}" -ne 0 ] && fail=1
rm -rf "${STATE}/cases_before"; cp -r aether_quant/_formal_cases "${STATE}/cases_before"
python3 aq_cli.py prove --regen-cases > "${STATE}/prove.log" 2>&1
code=$?; mark "PROVE exit ${code}"; [ "${code}" -ne 0 ] && fail=1
# the regenerated cases must equal the committed ones: a spec change that moved a case shows here
diff -r "${STATE}/cases_before" aether_quant/_formal_cases > "${STATE}/cases.diff" 2>&1
code=$?; mark "CASES_UNCHANGED exit ${code}"; [ "${code}" -ne 0 ] && fail=1
# every theorem rests on the standard axioms only (scripts/check_axioms.py)
python3 scripts/check_axioms.py > "${STATE}/axioms.log" 2>&1
code=$?; mark "AXIOMS exit ${code}"; [ "${code}" -ne 0 ] && fail=1
mark "PROVE_DONE fail=${fail}"
exit "${fail}"
