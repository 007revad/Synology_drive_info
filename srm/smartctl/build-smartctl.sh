#!/bin/bash
# Builds the static smartctl 7.5 binaries bundled in the Synology router (SRM) package:
#   smartctl-armv7-hf-static   ARMv7-A, Thumb-2, VFPv3-D16, hard-float  (ipq806x, dakota, hawkeye)
#   smartctl-aarch64-static    AArch64                                   (cypress)
# Cross-compiled on x86_64 Linux with Zig's bundled clang + musl libc, statically linked.
# Needs: python3 (with venv + pip), curl, tar.
# Usage: ./build-smartctl.sh [work-dir]      Output: <work-dir>/smartctl-*-static
set -euo pipefail

SM_VERSION="7.5"
SM_URL="https://github.com/smartmontools/smartmontools/releases/download/RELEASE_${SM_VERSION//./_}/smartmontools-${SM_VERSION}.tar.gz"
SM_SHA256="690b83ca331378da9ea0d9d61008c4b22dde391387b9bbad7f29387f2595f76e"
ZIG_VERSION="0.17.0"

mkdir -p "${1:-$PWD/smartctl-build}"
WORK="$(cd "${1:-$PWD/smartctl-build}" && pwd)"
cd "$WORK"

[ -x zig-venv/bin/python ] || python3 -m venv zig-venv
./zig-venv/bin/pip install -q "ziglang==${ZIG_VERSION}"
ZIG="$WORK/zig-venv/bin/python -m ziglang"

if [ ! -d src ]; then
    curl -fsSL -o "smartmontools-${SM_VERSION}.tar.gz" "$SM_URL"
    echo "${SM_SHA256}  smartmontools-${SM_VERSION}.tar.gz" | sha256sum -c -
    mkdir src && tar -xzf "smartmontools-${SM_VERSION}.tar.gz" -C src --strip-components=1
fi

# Compiler wrappers, found through PATH so that no build directory path ends up
# inside the binary (smartctl --version prints its configure arguments).
# The ARMv7 target matches the SRM busybox: Tag_CPU_arch v7, Thumb-2, VFPv3-D16, hard-float, no NEON.
mkdir -p tools
cat > tools/cc-armv7 <<EOT
#!/bin/sh
exec $ZIG cc -target arm-linux-musleabihf -mcpu=generic+v7a+vfp3d16-neon-d32 -mfloat-abi=hard "\$@"
EOT
cat > tools/cxx-armv7 <<EOT
#!/bin/sh
exec $ZIG c++ -target arm-linux-musleabihf -mcpu=generic+v7a+vfp3d16-neon-d32 -mfloat-abi=hard "\$@"
EOT
cat > tools/cc-aarch64 <<EOT
#!/bin/sh
exec $ZIG cc -target aarch64-linux-musl "\$@"
EOT
cat > tools/cxx-aarch64 <<EOT
#!/bin/sh
exec $ZIG c++ -target aarch64-linux-musl "\$@"
EOT
chmod +x tools/*
export PATH="$WORK/tools:$PATH"

build() {   # build <output-name> <wrapper-suffix> <host-triple>
    local out="$1" sfx="$2" host="$3"
    rm -rf "build-$out" && cp -r src "build-$out" && cd "build-$out"
    export CC="cc-$sfx" CXX="cxx-$sfx" AR="ar-$sfx" RANLIB="ranlib-$sfx"
    export CFLAGS="-Os -w" CXXFLAGS="-Os -w" LDFLAGS="-static"
    ./configure --host="$host" --build=x86_64-linux-gnu \
        --without-libcap-ng --without-selinux --without-libsystemd \
        --disable-dependency-tracking > configure.log 2>&1
    make -j"$(nproc)" smartctl > make.log 2>&1
    cp smartctl "$WORK/$out"
    cd "$WORK"
}

for t in armv7 aarch64; do
    printf '#!/bin/sh\nexec %s ar "$@"\n' "$ZIG" > "tools/ar-$t"
    printf '#!/bin/sh\nexec %s ranlib "$@"\n' "$ZIG" > "tools/ranlib-$t"
    chmod +x "tools/ar-$t" "tools/ranlib-$t"
done
build smartctl-armv7-hf-static armv7   arm-linux-musleabihf
build smartctl-aarch64-static  aarch64 aarch64-linux-musl
sha256sum smartctl-armv7-hf-static smartctl-aarch64-static
