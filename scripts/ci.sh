#!/usr/bin/env bash

set -euo pipefail

sudo tar -C / -xf zstd.tar.gz
./zstd -d deps.tar.zst
sudo tar -C / -xf deps.tar
rm deps.tar
sudo cp /root/shell.sh "$HOME"
bash -c '. "$HOME"/shell.sh && ./scripts/run_tests.sh'
