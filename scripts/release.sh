#!/usr/bin/env bash
#
# Builds release artifacts and, optionally, publishes the GitHub release.
#
#   ./scripts/release.sh            build artifacts into dist/
#   ./scripts/release.sh --publish  build, then create/update the GitHub release
#
# Artifacts:
#   codeguard                  the CLI, ready to chmod +x and run
#   codeguard-<version>.tar.gz full source, deterministic (built from the tag)
#   SHA256SUMS                 checksums for both - `codeguard -u` requires this
#                              and refuses to update without it
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

DIST="dist"
CLI="src/cli/codeguard.sh"
REPO="${CODEGUARD_REPO:-TarzEH/codeguard}"
PUBLISH=0
[ "${1:-}" = "--publish" ] && PUBLISH=1

VERSION=$(awk -F'"' '/^CODEGUARD_VERSION=/{print $2}' "$CLI")
[ -n "$VERSION" ] || { echo "could not read CODEGUARD_VERSION from $CLI" >&2; exit 1; }
TAG="v$VERSION"

echo "building codeguard $TAG"

# The tag must exist and match the working tree, otherwise the tarball would
# not correspond to what the release claims to ship.
if ! git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "tag $TAG does not exist - create it first: git tag -a $TAG" >&2
    exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
    echo "working tree is dirty - commit before building a release" >&2
    exit 1
fi

rm -rf "$DIST" && mkdir -p "$DIST"

# 1. The CLI as a standalone file. It is a single self-contained script, so
#    this *is* the installable artifact - no unpacking required.
cp "$CLI" "$DIST/codeguard"
chmod 0755 "$DIST/codeguard"

# 2. Full source, generated from the tag so it is reproducible.
git archive --format=tar.gz \
    --prefix="codeguard-$VERSION/" \
    -o "$DIST/codeguard-$VERSION.tar.gz" \
    "$TAG"

# 3. Checksums. `codeguard -u` downloads this and refuses to install anything
#    that is absent from it or does not match.
(
    cd "$DIST"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum codeguard "codeguard-$VERSION.tar.gz" > SHA256SUMS
    else
        shasum -a 256 codeguard "codeguard-$VERSION.tar.gz" > SHA256SUMS
    fi
)

echo
echo "artifacts in $DIST/:"
while read -r sum name; do
    printf '  %-28s %s  %s\n' "$name" "${sum:0:16}…" "$(du -h "$DIST/$name" | cut -f1)"
done < "$DIST/SHA256SUMS"
echo

if [ "$PUBLISH" = "0" ]; then
    echo "not published. Re-run with --publish to create the GitHub release."
    exit 0
fi

command -v gh >/dev/null 2>&1 || { echo "gh CLI is required to publish" >&2; exit 1; }

NOTES_FILE=$(mktemp)
trap 'rm -f "$NOTES_FILE"' EXIT
{
    echo "## Install"
    echo
    echo '```bash'
    echo "curl -fsSLO https://github.com/$REPO/releases/download/$TAG/codeguard"
    echo "curl -fsSLO https://github.com/$REPO/releases/download/$TAG/SHA256SUMS"
    echo "shasum -a 256 -c SHA256SUMS --ignore-missing"
    echo "chmod +x codeguard && sudo mv codeguard /usr/local/bin/"
    echo '```'
    echo
    echo "Requires \`curl\` and \`jq\`. For the full cluster, clone the repo and run \`./install.sh\`."
    echo
    echo "Already installed? \`codeguard -u\` verifies this release against \`SHA256SUMS\` before replacing itself."
    echo
    if [ -f CHANGELOG.md ]; then
        # Everything between this version's heading and the next one.
        awk -v v="$VERSION" '
            $0 ~ "^## \\[" v "\\]" {p=1; print "## Changes"; next}
            p && /^## \[/ {exit}
            p {print}
        ' CHANGELOG.md
    fi
} > "$NOTES_FILE"

if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
    echo "updating existing release $TAG"
    gh release upload "$TAG" "$DIST"/* --repo "$REPO" --clobber
    gh release edit "$TAG" --repo "$REPO" --notes-file "$NOTES_FILE"
else
    echo "creating release $TAG"
    gh release create "$TAG" "$DIST"/* \
        --repo "$REPO" \
        --title "codeguard $TAG" \
        --notes-file "$NOTES_FILE"
fi

echo
echo "published: https://github.com/$REPO/releases/tag/$TAG"
