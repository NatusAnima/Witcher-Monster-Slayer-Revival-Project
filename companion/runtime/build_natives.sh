#!/bin/sh
# Build the two native pieces of the phone runtime (Alpine 3.22, aarch64) into local/cache/natives/:
#   osmium-4.3.1-cp312-cp312-linux_aarch64.whl  pyosmium for the index builder (PyPI only has glibc builds)
#   libseccompshim.so                          see seccomp_shim.c
#
# Runs on any x86_64 Linux (WSL included) without root or Docker: a static qemu-aarch64 and proot run
# an Alpine aarch64 root filesystem kept in ~/arm64. The first build takes a few minutes.
#   wsl -d Ubuntu -- sh companion/runtime/build_natives.sh      (from the repository root)
set -eu
REPO=$(cd "$(dirname "$0")/../.." && pwd)
OUT="$REPO/local/cache/natives"
D="$HOME/arm64"
mkdir -p "$D" "$OUT" && cd "$D"
[ -x qemu-aarch64 ] || { curl -fsSL -o qemu-aarch64 https://github.com/multiarch/qemu-user-static/releases/download/v7.2.0-1/qemu-aarch64-static && chmod +x qemu-aarch64; }
[ -x proot ] || { curl -fsSL -o proot https://proot.gitlab.io/proot/bin/proot && chmod +x proot; }
if [ ! -d rootfs/etc ]; then
  version=$(curl -fsSL https://dl-cdn.alpinelinux.org/alpine/v3.22/releases/aarch64/latest-releases.yaml \
    | awk '/flavor: alpine-minirootfs/{f=1} f&&/version:/{print $2; exit}')
  mkdir -p rootfs && curl -fsSL "https://dl-cdn.alpinelinux.org/alpine/v3.22/releases/aarch64/alpine-minirootfs-$version-aarch64.tar.gz" | tar -xz -C rootfs
  cp /etc/resolv.conf rootfs/etc/resolv.conf
fi
cp "$REPO/companion/runtime/seccomp_shim.c" rootfs/root/seccomp_shim.c
cat > rootfs/root/build-natives.sh <<'IN'
set -eu
apk add --no-cache python3 python3-dev py3-pip build-base cmake samurai expat-dev bzip2-dev zlib-dev lz4-dev
gcc -shared -fPIC -O2 -s -o /root/libseccompshim.so /root/seccomp_shim.c
[ -f /root/wheels/osmium-4.3.1-cp312-cp312-linux_aarch64.whl ] && exit 0
[ -d /root/venv ] || python3 -m venv /root/venv
CMAKE_BUILD_PARALLEL_LEVEL=$(nproc) /root/venv/bin/pip wheel --no-deps osmium==4.3.1 -w /root/wheels
IN
./proot -q ./qemu-aarch64 -r rootfs -b /dev -b /proc -b /sys -w /root /bin/sh /root/build-natives.sh
cp rootfs/root/libseccompshim.so rootfs/root/wheels/osmium-4.3.1-cp312-cp312-linux_aarch64.whl "$OUT/"
ls -la "$OUT"
