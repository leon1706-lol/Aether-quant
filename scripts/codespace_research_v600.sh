#!/usr/bin/env bash
# V6.0.0: the three research runs behind the main book, crypto fees and the forex sleeve (rules R-BOOK, R-CRYPTO, R-FX6),
# on the Codespace (the 4 GB dev PC cannot hold the scored frames). Resumable per script (RESUME=1 skips finished outputs).
#
#   bash scripts/codespace_research_v600.sh [dataset]       default ml/datasets/full_dataset.csv (the V6 four-split dataset)
set -uo pipefail
cd "$(dirname "$0")/.."
DATASET="${1:-ml/datasets/full_dataset.csv}"
mkdir -p ml/evaluation/v600
exec > >(tee -a ml/evaluation/v600/research_codespace.log) 2>&1
step() { echo "=== $(date -u +%FT%TZ) $*"; }
done_marker() { [ "${RESUME:-0}" = "1" ] && [ -f "$1" ]; }

done_marker ml/evaluation/v600/forex_research.json || { step "R-FX6 forex keep or drop"; python scripts/forex_keep_or_drop.py --dataset "${DATASET}"; }
done_marker ml/evaluation/v600/crypto_research.json || { step "R-CRYPTO fees"; python scripts/crypto_fee_research.py --dataset "${DATASET}"; }
done_marker ml/evaluation/v600/book_research.json || { step "R-BOOK main book variants"; python scripts/book_variant_research.py --dataset "${DATASET}"; }
step "DONE"
