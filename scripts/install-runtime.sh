#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
prefix=${GLASS_PREFIX:-"${XDG_DATA_HOME:-$HOME/.local/share}/noctalia-liquid-glass/runtime"}
# Stage Meson's complete assets/manifests first. Replace executable inodes
# atomically, so an already-running compositor is never truncated in place.
stage=$(mktemp -d "$repo/.build/install.XXXXXXXX")
meson install -C "$repo/.build/umbriel/build" --no-rebuild --destdir "$stage"
meson install -C "$repo/.build/noctalia-diagnose/build" --no-rebuild --destdir "$stage"
mkdir -p "$prefix/bin" "$prefix/share"
cp -a "$stage$prefix/share/." "$prefix/share/"
for program in umbriel noctalia; do
  install -m755 "$stage$prefix/bin/$program" "$prefix/bin/$program.next"
  mv -f "$prefix/bin/$program.next" "$prefix/bin/$program"
done
echo "Installed both runtimes into $prefix. Running processes were not restarted."
