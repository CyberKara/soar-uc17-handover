#!/usr/bin/env bash
# Create a GitHub Release for every connector package that does not have one.
#
# A connector version is a connectors/efficientip_ddi-v<version>.tgz that was
# added to git. Each one gets a release tagged v<version>, at the commit that
# added it, carrying that exact file read back out of git (never rebuilt), with
# the commit message as notes plus the package's sha256. Re-running is safe: a
# version that already has a release is skipped.
#
# Usage: tools/create_releases.sh [<git revision range>]
#   (no argument)  every package ever added -- a full backfill
#   A..B           only packages added in that range -- what CI passes on a push,
#                  so a release deleted on purpose is not quietly recreated
#
# Needs gh (logged in, or GH_TOKEN set) and a clone with full history and tags.
# DRY_RUN=1 prints what would be created and touches nothing.
#
# Refuses to release a package whose filename version disagrees with the
# app_version inside it: that file would be published under the wrong name.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

range="${1:-}"
pattern='connectors/efficientip_ddi-v*.tgz'

# "<commit> <path>" for each package added in range, oldest first. --no-renames
# keeps a moved file from being reported as a rename instead of an addition.
added=()
while read -r sha path; do
  added+=("$sha $path")
done < <(
  git log --reverse --no-renames --diff-filter=A --name-only \
    --format='commit %H' ${range:+"$range"} -- "$pattern" |
    awk '/^commit /{c=$2; next} NF{print c, $0}'
)

if [ "${#added[@]}" -eq 0 ]; then
  echo "no new connector packages${range:+ in $range}"
  exit 0
fi

# Only the highest version may claim "Latest". Compared against the versions
# already tagged as well, so releasing an older line later cannot displace it.
versions=()
for entry in "${added[@]}"; do
  path=${entry#* }
  version=${path#connectors/efficientip_ddi-v}
  versions+=("${version%.tgz}")
done
highest=$(
  { printf '%s\n' "${versions[@]}"; git tag -l 'v*' | sed 's/^v//'; } | sort -V | tail -n 1
)

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

run() {
  if [ "${DRY_RUN:-}" = "1" ]; then
    printf '    would run:'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

for entry in "${added[@]}"; do
  sha=${entry%% *}
  path=${entry#* }
  asset_name=${path#connectors/}
  version=${asset_name#efficientip_ddi-v}
  version=${version%.tgz}
  tag="v${version}"
  asset="$workdir/$asset_name"

  if [ "${DRY_RUN:-}" != "1" ] && gh release view "$tag" >/dev/null 2>&1; then
    echo "$tag: release already exists, skipping"
    continue
  fi

  git show "${sha}:${path}" >"$asset"

  inner=$(
    tar -xzOf "$asset" efficientip_ddi/efficientip_ddi.json |
      python3 -c 'import json, sys; print(json.load(sys.stdin)["app_version"])'
  )
  if [ "$inner" != "$version" ]; then
    echo "$tag: $asset_name says $version but the package's app_version is $inner -- not releasing" >&2
    exit 1
  fi

  checksum=$(sha256sum "$asset" | cut -d' ' -f1)

  notes="$workdir/notes-${version}.md"
  {
    git log -1 --format=%B "$sha" | grep -vE '^(Co-Authored-By|Claude-Session):' || true
    printf '\n---\n\n'
    printf 'Package: `%s`  \n' "$asset_name"
    printf 'sha256: `%s`  \n' "$checksum"
    printf 'Commit: %s\n\n' "$sha"
    printf 'Install with Apps > Install App in the SOAR web interface. SOAR refuses a\n'
    printf 'connector whose version is not newer than the one already installed.\n'
  } >"$notes"

  latest_flag="--latest=false"
  [ "$version" = "$highest" ] && latest_flag="--latest"

  echo "$tag -> ${sha:0:7} ($asset_name, sha256 ${checksum:0:12})"
  [ "${DRY_RUN:-}" = "1" ] && sed 's/^/    | /' "$notes"
  run gh release create "$tag" "$asset" \
    --target "$sha" \
    --title "efficientip_ddi v${version}" \
    --notes-file "$notes" \
    "$latest_flag"
done
