#!/usr/bin/env bash
# build-bundle.sh
# TODO nix; needs makeself, grep, head, echo, sed, chomd,rm, upx, strip, find, xargs, upx)

find client.dist -iname '*.so*' -print0 | xargs -0 -I {} strip -s {}
patchelf --set-interpreter './ld-musl-x86_64.so.1' client.dist/client.bin
upx client.dist/client.bin

makeself --nox11 --quiet --noprogress client.dist bundle.tmp "nacme_client" ./client.bin

# Get current skip value
skip=$(grep -a '^skip=' bundle.tmp | head -1 | cut -d'"' -f2)
new_skip=$((skip + 2))

# Inject set -- and update settings
cat <(head -n 1 bundle.tmp) \
	<(echo 'set -- "--" "$@"') \
	bundle.tmp >bundle

# Update skip and quiet
sed -i "s/skip=\"$skip\"/skip=\"$new_skip\"/" bundle
sed -i 's/quiet="n"/quiet="y"/' bundle

chmod +x bundle
rm bundle.tmp
