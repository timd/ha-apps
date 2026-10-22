#!/bin/sh
# Copy overflights/ to /addons/overflights/ on a Home Assistant server as a
# development App. The image line is removed, so the Supervisor builds it from
# the Dockerfile, and the name says "development".
# Usage: scripts/deploy-local.sh user@host [ssh options...]
set -eu
host=$1
shift
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git archive HEAD overflights | tar -x -C "$tmp"
sed -e '/^image:/d' -e 's/^name: Overflights$/name: Overflights (development)/' \
  "$tmp/overflights/config.yaml" > "$tmp/config.yaml"
mv "$tmp/config.yaml" "$tmp/overflights/config.yaml"
# COPYFILE_DISABLE keeps macOS tar from adding ._ metadata files.
COPYFILE_DISABLE=1 tar -C "$tmp" -c overflights | ssh "$@" "$host" \
  'rm -rf /tmp/overflights-stage && mkdir /tmp/overflights-stage && tar -x -C /tmp/overflights-stage && sudo rm -rf /addons/overflights && sudo cp -r /tmp/overflights-stage/overflights /addons/'
echo "Copied. In Home Assistant: App store → Check for updates, then Update or Rebuild."
