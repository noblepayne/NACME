#!/usr/bin/env bash
sudo podman run --rm -v $PWD:/app -w /app --name nacme_test -it --network none -u ubuntu nacme_test /app/scripts/ci.sh
