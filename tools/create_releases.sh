#!/usr/bin/env bash
# Create one GitHub Release per connector version in this repo's history.
#
# Each release is tagged at the commit that introduced that version's .tgz and
# carries that exact file, read back out of git rather than rebuilt, so the
# asset is byte-identical to what the repo has always held. Re-running is safe:
# a version whose release already exists is skipped.
#
# Needs gh, logged in (locally) or with GH_TOKEN set (in Actions), and a clone
# with full history. DRY_RUN=1 prints what would be created and touches nothing.
#
# v1.0.2, v1.0.7 and v1.0.9 are absent on purpose: they were never exported to
# this repo, so there is no package to release.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# version  commit that first carried connectors/efficientip_ddi-v<version>.tgz
RELEASES=(
  "1.0.0  010f30aa1dd24d1bfb9137797c74083d8bedf0de"
  "1.0.1  c9f985abcfdccb323817d08bb78a216424fe00c7"
  "1.0.3  9ea4507d8b4fecc856b68bfd2b18d89ed8d01cbc"
  "1.0.4  433349f226d33ac4abc9823398f1b70674252f0b"
  "1.0.5  e9782d599d19df69b5ac52422b0eed71258815b9"
  "1.0.6  b0d3aac1bb0467943197d5973841422d0863f230"
  "1.0.8  88cf260a897e0abcd2a3462f844049d12100e413"
  "1.0.10 472f291d57404f98c3c79319cf98bde4d9040c61"
  "1.0.11 7f051043ac10dd15d775c0920d0f31ea2b44de29"
)
LATEST="1.0.11"

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

run() {
  if [ "${DRY_RUN:-}" = "1" ]; then
    printf '    would run:'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

for entry in "${RELEASES[@]}"; do
  read -r version sha <<<"$entry"
  tag="v${version}"
  asset_name="efficientip_ddi-v${version}.tgz"
  asset="$workdir/$asset_name"

  if [ "${DRY_RUN:-}" != "1" ] && gh release view "$tag" >/dev/null 2>&1; then
    echo "$tag: release already exists, skipping"
    continue
  fi

  # The commit must really hold this package; a wrong SHA here would publish
  # some other version's file under this tag.
  git cat-file -e "${sha}:connectors/${asset_name}"
  git show "${sha}:connectors/${asset_name}" >"$asset"
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
  [ "$version" = "$LATEST" ] && latest_flag="--latest"

  echo "$tag -> ${sha:0:7} ($asset_name, sha256 ${checksum:0:12})"
  [ "${DRY_RUN:-}" = "1" ] && sed 's/^/    | /' "$notes"
  run gh release create "$tag" "$asset" \
    --target "$sha" \
    --title "efficientip_ddi v${version}" \
    --notes-file "$notes" \
    "$latest_flag"
done
