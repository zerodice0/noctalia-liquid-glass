#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
src="$repo/.build/noctalia-diagnose"
prefix=${GLASS_PREFIX:-"${XDG_DATA_HOME:-$HOME/.local/share}/noctalia-liquid-glass/runtime"}
pin=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$repo/noctalia-upstream.json")
if [[ ! -d $src/.git ]]; then
  mkdir -p "$src"
  git -C "$src" init -q
  git -C "$src" remote add origin https://github.com/noctalia-dev/noctalia.git
  git -C "$src" fetch --depth 1 origin "$pin"
  git -C "$src" checkout --detach FETCH_HEAD
fi
[[ $(git -C "$src" rev-parse HEAD) == "$pin" ]] || { echo 'Unexpected Noctalia revision.' >&2; exit 1; }
if ! git -C "$src" apply --reverse --check "$repo/patches/noctalia-liquid-glass.patch" 2>/dev/null; then
  [[ -z $(git -C "$src" status --porcelain --untracked-files=no) ]] || { echo 'Unrecognized Noctalia edits; refusing to overwrite.' >&2; exit 1; }
  git -C "$src" apply --check "$repo/patches/noctalia-liquid-glass.patch"
  git -C "$src" apply "$repo/patches/noctalia-liquid-glass.patch"
fi
deps="$repo/.build/deps"
mkdir -p "$deps"
if [[ ! -f /usr/include/stb/stb_image_resize2.h ]]; then
  pkg="$deps/stb.pkg.tar.zst"
  if [[ ! -f $pkg ]]; then
    curl -fL --max-time 120 -o "$pkg" 'https://archlinux.cachyos.org/repo/extra/os/x86_64/stb-20260415.205329.g31c1ad374564-1-any.pkg.tar.zst'
  fi
  printf '%s  %s\n' '286f2694dccf92acd197940b6ca068d3a6d5c763123e02a0e4fe26e611a97f25' "$pkg" | sha256sum -c -
  bsdtar -xf "$pkg" -C "$deps" usr/include
fi
# build.sh supplies local nlohmann-json if the system package is absent.
export CMAKE_PREFIX_PATH="$deps/usr${CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}"
export C_INCLUDE_PATH="$deps/usr/include${C_INCLUDE_PATH:+:$C_INCLUDE_PATH}"
export CPLUS_INCLUDE_PATH="$deps/usr/include${CPLUS_INCLUDE_PATH:+:$CPLUS_INCLUDE_PATH}"
args=(--buildtype=release --prefix="$prefix" --wrap-mode=nodownload -Dtests=enabled)
if [[ -f $src/build/build.ninja ]]; then args=(--reconfigure "${args[@]}"); fi
meson setup "$src/build" "$src" "${args[@]}"
meson compile -C "$src/build" -j "${GLASS_JOBS:-4}" noctalia
echo "Built Noctalia. Run scripts/install-runtime.sh to install both runtimes without restarting the session."
