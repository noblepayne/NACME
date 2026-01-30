#!/usr/bin/env sh
cp /app/nacme/client.py .
./venv/bin/nuitka --mode=standalone --static-libpython=no ./client.py
cp /lib/ld-musl-x86_64.so.1 ./client.dist
mv ./client.dist /app
