#!/usr/bin/env bash

set -euo pipefail

# TODO: assumes nix, tar, curl (m2), ln, unlink

SYSTEM=$(nix eval --raw --impure --expr "builtins.currentSystem")

echo "~~~ TOOLS ~~~"
nix build --no-link nixpkgs#ripgrep
nix build nixpkgs#zstd --out-link zstd
TOOLSPATH=$(nix eval -I "nixpkgs=flake:nixpkgs" --impure --raw --expr "let pkgs = import <nixpkgs> {}; in pkgs.lib.makeBinPath [pkgs.ripgrep pkgs.zstd]")
export PATH="$TOOLSPATH:$PATH"

echo "~~~ SKELETON ~~~"
mkdir -p staging/root

echo "~~~ nix ~~~"
# TODO: only do if dir not found
mkdir -p staging/nix/store
nix build --no-link --impure .#devShells."$SYSTEM".testenv
nix print-dev-env --impure .#testenv >staging/root/shell.sh
nix path-info --impure -r .#devShells."$SYSTEM".testenv | xargs -P0 -I {} cp -r {} staging/nix/store

echo "~~~ find & replace ~~~"
./scripts/replace.sh "$PWD" "/tmp/ci_test_runtime" staging || true
./scripts/replace.sh "$XDG_RUNTIME_DIR" "/tmp/ci_test_runtime" staging || true

echo "~~~ tar ~~~"
tar -cf deps.tar -C staging .

echo "~~~ compress ~~~"
zstd deps.tar
rm deps.tar

echo "~~~ zstd ~~~"
#nix build nixpkgs#zstd --out-link zstd  # done in ripgrep
ln -s "$(realpath zstd-bin/bin/zstd)" zstd
tar cfz zstd.tar.gz -T<(nix path-info -r ./zstd-bin)
unlink zstd-bin
unlink zstd-man
