#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
src="$repo/.build/umbriel"
prefix=${GLASS_PREFIX:-"${XDG_DATA_HOME:-$HOME/.local/share}/noctalia-liquid-glass/runtime"}
pin=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$repo/upstream.json")
url=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["url"])' "$repo/upstream.json")
if [[ ! -d $src/.git ]]; then
  mkdir -p "$src"
  git -C "$src" init -q
  git -C "$src" remote add origin "$url"
  git -C "$src" fetch --depth 1 origin "$pin"
  git -C "$src" checkout --detach FETCH_HEAD
fi
[[ $(git -C "$src" rev-parse HEAD) == "$pin" ]] || { echo 'Unexpected upstream revision; use a fresh .build directory.' >&2; exit 1; }
if git -C "$src" apply --reverse --check "$repo/patches/umbriel-liquid-glass.patch" 2>/dev/null; then
  echo 'Glass patch is already applied.'
else
  [[ -z $(git -C "$src" status --porcelain --untracked-files=no) ]] || { echo 'Upstream has unrecognized edits; refusing to overwrite.' >&2; exit 1; }
  git -C "$src" apply --check "$repo/patches/umbriel-liquid-glass.patch"
  git -C "$src" apply "$repo/patches/umbriel-liquid-glass.patch"
fi
# Optional, local-only header dependency for machines without nlohmann-json.
# No root install, and the archive is pinned by SHA256 before extraction.
if ! pkg-config --exists nlohmann_json; then
  deps="$repo/.build/deps"
  mkdir -p "$deps"
  pkg="$deps/nlohmann-json.pkg.tar.zst"
  if [[ ! -f $pkg ]]; then
    curl -fL --max-time 120 -o "$pkg" 'https://archlinux.cachyos.org/repo/extra/os/x86_64/nlohmann-json-3.12.0-2-any.pkg.tar.zst'
  fi
  printf '%s  %s\n' '55968568ee1c8f3ffe691b51d4f6660acb40ee82f474d41fc6e18c571e87ddc4' "$pkg" | sha256sum -c -
  bsdtar -xf "$pkg" -C "$deps" usr/include usr/share/cmake
  export CMAKE_PREFIX_PATH="$deps/usr${CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}"
fi
args=(--buildtype=release --prefix="$prefix" --wrap-mode=nodownload -Dtests=enabled)
if [[ -f $src/build/build.ninja ]]; then args=(--reconfigure "${args[@]}"); fi
meson setup "$src/build" "$src" "${args[@]}"
meson compile -C "$src/build" -j "${GLASS_JOBS:-4}"
meson test -C "$src/build" --print-errorlogs
echo "Built and unit-tested: $src/build/umbriel"
echo "Install runtime (no root): meson install -C '$src/build' --no-rebuild"
