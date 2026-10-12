#!/bin/bash
# Builds the static bash 5.2 binaries bundled in the Synology router (SRM) package:
#   bash-armv7-hf-static   ARMv7-A, Thumb-2, VFPv3-D16, hard-float  (ipq806x, dakota, hawkeye)
#   bash-aarch64-static    AArch64                                   (cypress)
# Cross-compiled on x86_64 Linux with Zig's bundled clang + musl libc (Zig 0.17.0).
# Needs: python3 (with venv + pip), git, gcc and make (for bash's build-time helper tools).
# Usage: ./build-bash.sh [work-dir]      Output: <work-dir>/bash-*-static
set -euo pipefail

BASH_REPO="https://github.com/mirror/bash.git"
BASH_TAG="bash-5.2"
BASH_COMMIT="74091dd4e8086db518b30df7f222691524469998"
ZIG_VERSION="0.17.0"

WORK="$(mkdir -p "${1:-$PWD/bash-build}" && cd "${1:-$PWD/bash-build}" && pwd)"
cd "$WORK"

[ -x zig-venv/bin/python ] || python3 -m venv zig-venv
./zig-venv/bin/pip install -q "ziglang==${ZIG_VERSION}"
ZIG="$WORK/zig-venv/bin/python -m ziglang"

[ -d src ] || git clone -q --depth 1 --branch "$BASH_TAG" "$BASH_REPO" src
[ "$(git -C src rev-parse HEAD)" = "$BASH_COMMIT" ] || { echo "unexpected bash commit" >&2; exit 1; }

# Compiler wrappers so configure sees a single CC.
# The ARMv7 target matches the SRM busybox: Tag_CPU_arch v7, Thumb-2, VFPv3-D16, hard-float, no NEON.
cat > cc-armv7 <<EOT
#!/bin/sh
exec $ZIG cc -target arm-linux-musleabihf -mcpu=generic+v7a+vfp3d16-neon-d32 -mfloat-abi=hard "\$@"
EOT
cat > cc-aarch64 <<EOT
#!/bin/sh
exec $ZIG cc -target aarch64-linux-musl "\$@"
EOT
chmod +x cc-armv7 cc-aarch64

build() {   # build <output-name> <cc-wrapper> <host-triple>
    local out="$1" ccw="$2" host="$3"
    rm -rf "build-$out" && cp -r src "build-$out" && cd "build-$out"
    export CC="$WORK/$ccw" AR="$ZIG ar" RANLIB="$ZIG ranlib"
    export CFLAGS="-Os -std=gnu99 -fcommon -fno-strict-aliasing -w" LDFLAGS="-static"
    export bash_cv_wexitstatus_offset=8      # can't be probed when cross-compiling
    ./configure --host="$host" --build=x86_64-linux-gnu --enable-static-link \
        --without-bash-malloc --disable-nls --disable-rpath \
        --disable-readline --disable-history --disable-bang-history > configure.log 2>&1
    make -j"$(nproc)" CC_FOR_BUILD=gcc CFLAGS_FOR_BUILD="-O1 -w" > make.log 2>&1
    cp bash "$WORK/$out"          # the linker already strips it
    cd "$WORK"
}

build bash-armv7-hf-static cc-armv7   arm-linux-musleabihf
build bash-aarch64-static  cc-aarch64 aarch64-linux-musl
sha256sum bash-armv7-hf-static bash-aarch64-static
