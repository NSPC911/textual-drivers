#!/usr/bin/env bash
set -euo pipefail

WIKI_URL="https://github.com/NSPC911/textual-drivers.wiki.git"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

git clone "$WIKI_URL" "$TMP"
cp docs/*.md "$TMP/"
cd "$TMP"
git add -A
git diff --cached --quiet && { echo "Wiki already up to date."; exit 0; }
git commit -m "Sync docs from main repo"
git push
echo "Wiki updated."
