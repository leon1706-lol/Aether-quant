#!/usr/bin/env bash
# Summary of ml/memwatch.log: lowest available memory (with time), the last samples where a python process was the top
# consumer, and the first samples after it vanished.
cd "$(dirname "$0")/.."
L=ml/memwatch.log
echo "samples: $(wc -l < $L)"
echo "lowest avail:"; sed 's/avail=\([0-9]*\)MB.*/\1 &/' $L | sort -n | head -3 | cut -c1-80
last=$(grep -n 'python' $L | tail -1 | cut -d: -f1)
echo "last python-top sample is line ${last}:"
sed -n "$((last-4)),$((last+4))p" $L
