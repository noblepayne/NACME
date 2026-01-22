#!/usr/bin/env sh
export OLDSHELL=$SHELL
nix develop -c $SHELL
