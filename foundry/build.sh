#!/usr/bin/env bash
# Build the Foundry module release files into foundry/dist/:
#   module.json            (the manifest Foundry installs from)
#   rpgnotes-recorder.zip  (module.json + scripts/ at the zip root)
# Bump "version" and the "download" URL in module.json first, then upload both
# to a GitHub release named foundry-v<version>.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf dist && mkdir -p dist
(cd rpgnotes-recorder && zip -qr ../dist/rpgnotes-recorder.zip module.json scripts)
cp rpgnotes-recorder/module.json dist/
version=$(python3 -c 'import json; print(json.load(open("dist/module.json"))["version"])')
echo "Built foundry/dist for v$version:"
ls -l dist
echo "Publish: gh release create foundry-v$version foundry/dist/* --title \"Foundry recorder v$version\""
