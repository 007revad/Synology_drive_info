#!/bin/bash
# Adds static smartctl 7.5 binaries to ui/bin/ inside a built .spk.
#
# Usage: add-smartctl.sh <package.spk> <smartctl-binary-name>...
#   e.g. add-smartctl.sh dist/Drive_Info-armv8-v2.4.72-DSM-7.x.spk smartctl-aarch64-static
#
# The binaries come from srm/smartctl/ in the repo (outside src/, so the package
# builder never sees them). postinst keeps the one that runs on the NAS or router,
# symlinks ui/bin/smartctl7 to it and deletes the others.
#
# The spk is rewritten in place. package.tgz keeps its compression (the package
# builder makes xz, SRM needs gzip and handles that in its own step). INFO's
# checksum and extractsize are updated to match the new package.tgz.
set -euo pipefail

[ $# -ge 2 ] || { echo "Usage: $0 <package.spk> <smartctl-binary-name>..." >&2; exit 2; }

spk="$(realpath "$1")"; shift
src="${GITHUB_WORKSPACE:-$PWD}/srm/smartctl"

[ -f "$spk" ] || { echo "::error::$spk not found"; exit 1; }

tmpdir=$(mktemp -d)
pkgdir=$(mktemp -d)
trap 'rm -rf "$tmpdir" "$pkgdir"' EXIT

tar -xf "$spk" -C "$tmpdir"
[ -f "$tmpdir/package.tgz" ] || { echo "::error::package.tgz not found in $spk"; exit 1; }
[ -f "$tmpdir/INFO" ]        || { echo "::error::INFO not found in $spk"; exit 1; }

# Repack with the same compression the package builder used
if xz -t "$tmpdir/package.tgz" 2>/dev/null; then comp="J"; else comp="z"; fi

tar -xf "$tmpdir/package.tgz" -C "$pkgdir"
[ -d "$pkgdir/ui/bin" ] || { echo "::error::ui/bin not found in package.tgz of $spk"; exit 1; }

for b in "$@"; do
    [ -f "$src/$b" ] || { echo "::error::$src/$b is missing"; exit 1; }
    cp "$src/$b" "$pkgdir/ui/bin/$b"
    chmod 555 "$pkgdir/ui/bin/$b"
done

# Files must be root-owned in the tar, otherwise the runner's uid (1001) ends up
# on the NAS and a local user with that uid could edit scripts that run as root.
(cd "$pkgdir" && tar -c${comp}f "$tmpdir/package.tgz" \
    --owner=0 --group=0 --numeric-owner $(ls -A))

md5=$(md5sum "$tmpdir/package.tgz" | cut -d' ' -f1)
sed -i -E "s/^checksum=\".*\"/checksum=\"${md5}\"/" "$tmpdir/INFO"
sed -i -E "s/^extractsize=\".*\"/extractsize=\"$(du -sk "$pkgdir" | cut -f1)\"/" "$tmpdir/INFO"
for k in checksum extractsize; do
    grep -q "^${k}=" "$tmpdir/INFO" || { echo "::error::$k missing from INFO"; exit 1; }
done

tar -cf "$spk" -C "$tmpdir" $(ls "$tmpdir")
echo "Added to $(basename "$spk"): $*"
