#!/usr/bin/env bash
# Inspect the actual packaged image before any version/latest tags are published.
set -euo pipefail
image=${1:?image reference required}
context=${2:?Docker context required}
version=${3:?release version required}
upstream_sha=${4:?upstream SHA required}
version=${version#v}

binary_sha=$(sha256sum "$context/sub2api" | cut -d ' ' -f 1)
pricing_sha=$(sha256sum "$context/backend/resources/model-pricing/model_prices_and_context_window.json" | cut -d ' ' -f 1)
platform=$(docker image inspect "$image" --format '{{.Os}}/{{.Architecture}}')
[[ "$platform" == linux/amd64 ]]

# Exercise the real entrypoint, including its privilege drop.
version_output=$(docker run --rm "$image" -version 2>&1)
[[ "$version_output" == *"Sub2API $version (commit: $upstream_sha,"* ]]

docker run --rm \
  -e EXPECTED_BINARY_SHA="$binary_sha" -e EXPECTED_PRICING_SHA="$pricing_sha" \
  "$image" sh -eu -c '
    test "$(id -u)" != 0
    test "$(id -un)" = sub2api
    test "$(sha256sum /app/sub2api | cut -d " " -f 1)" = "$EXPECTED_BINARY_SHA"
    test "$(sha256sum /app/resources/model-pricing/model_prices_and_context_window.json | cut -d " " -f 1)" = "$EXPECTED_PRICING_SHA"
    test -w /app
    test -w /app/data
    update_dir=$(mktemp -d /app/.sub2api-update-XXXXXX)
    trap "rm -rf \"$update_dir\"" EXIT
    cp /app/sub2api "$update_dir/current"
    mv "$update_dir/current" "$update_dir/backup"
    cp /app/sub2api "$update_dir/new"
    mv "$update_dir/new" "$update_dir/current"
    /app/sub2api -version
    pg_dump --version
    psql --version
  '
