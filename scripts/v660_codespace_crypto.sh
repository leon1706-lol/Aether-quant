#!/usr/bin/env bash
# V6.6.0: the Binance root on the training Codespace (wired, 16 GB), then selection. Resumes if rerun. Poll /tmp/aq_v660/status.
set -u
OUT=/tmp/aq_v660
mkdir -p "${OUT}"
echo "$(date -u +%FT%TZ) DEPS" >> "${OUT}/status"
python3 -m pip install --quiet --user pyarrow requests scikit-learn > "${OUT}/pip.log" 2>&1
python3 scripts/build_crypto_wide_root.py --out data_crypto_wide > "${OUT}/crypto.log" 2>&1
code=$?
echo "$(date -u +%FT%TZ) CRYPTO exit ${code}" >> "${OUT}/status"
[ "${code}" -eq 0 ] || exit "${code}"
sed -i 's/\r$//' scripts/v660_codespace_selection.sh
bash scripts/v660_codespace_selection.sh
