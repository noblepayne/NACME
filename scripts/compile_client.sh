#!/usr/bin/env sh
cp /app/nacme/client.py .
./venv/bin/nuitka --mode=standalone --static-libpython=no ./client.py
# TODO: copy ld
