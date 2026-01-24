#!/usr/bin/env bash

set -euo pipefail

sudo podman build -t nacme_test -f Containerfile.tests
