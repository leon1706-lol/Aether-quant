#!/usr/bin/env bash
# Pack the small evaluation reports (json + the Monte Carlo curves) into /tmp/eval_pack.tgz for scp; datasets/cache stay.
cd "$(dirname "$0")/.."
tar czf /tmp/eval_pack.tgz ml/evaluation/*.json ml/evaluation/*.npz 2> /dev/null
ls -la --time-style=+%F_%T /tmp/eval_pack.tgz | cut -c1-100
tar tzf /tmp/eval_pack.tgz | wc -l
