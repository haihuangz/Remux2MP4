#!/usr/bin/env bash
# Build a slim GPL FFmpeg for mkv2mp4 inside an MSYS2 UCRT64 shell.
#
# Required MSYS2 packages (pacman -S --needed):
#   mingw-w64-ucrt-x86_64-gcc
#   mingw-w64-ucrt-x86_64-binutils
#   mingw-w64-ucrt-x86_64-nasm
#   mingw-w64-ucrt-x86_64-pkgconf
#   mingw-w64-ucrt-x86_64-libx264
#   mingw-w64-ucrt-x86_64-x265
#   mingw-w64-ucrt-x86_64-dav1d
#   mingw-w64-ucrt-x86_64-zlib
#   make
#   diffutils
#
# Usage: build_ffmpeg.sh <ffmpeg-X.Y.Z.tar.xz> <work-dir> <install-dir> [shared|static]
# Env:   JOBS (default: nproc)

set -euo pipefail

if [ $# -lt 3 ]; then
    echo "usage: $0 <ffmpeg-tarball> <work-dir> <install-dir> [shared|static]" >&2
    exit 2
fi

TARBALL=$(realpath "$1")
WORK=$(realpath -m "$2")
PREFIX=$(realpath -m "$3")
MODE=${4:-shared}
JOBS=${JOBS:-$(nproc)}

if [ "${MSYSTEM:-}" != "UCRT64" ]; then
    echo "run this inside an MSYS2 UCRT64 shell" >&2
    exit 2
fi

mkdir -p "$WORK/pkgconfig"
sed 's/ -lgcc_s//g' "$(pkg-config --variable=pcfiledir x265)/x265.pc" > "$WORK/pkgconfig/x265.pc"
export PKG_CONFIG_PATH="$WORK/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"

NAME=$(basename "$TARBALL" .tar.xz)
mkdir -p "$WORK"
rm -rf "${WORK:?}/$NAME"
tar -xJf "$TARBALL" -C "$WORK"
cd "$WORK/$NAME"

case "$MODE" in
    shared) LINK=(--enable-shared --disable-static) ;;
    static) LINK=(--disable-shared --enable-static) ;;
    *) echo "mode must be shared or static" >&2; exit 2 ;;
esac

CONFIGURE=(
    ./configure
    --prefix="$PREFIX"
    "${LINK[@]}"
    --enable-gpl
    --disable-autodetect
    --disable-network
    --disable-devices
    --disable-hwaccels
    --disable-ffplay
    --disable-doc
    --disable-debug
    --enable-w32threads
    --enable-zlib
    --enable-libx264
    --enable-libx265
    --enable-libdav1d
    --pkg-config-flags=--static
    --extra-cflags=-O2
    --extra-ldflags="-static -static-libgcc -static-libstdc++"
)

printf '%q ' "${CONFIGURE[@]}" > "$WORK/configure-command.txt"
echo >> "$WORK/configure-command.txt"

"${CONFIGURE[@]}"
make -j"$JOBS"
make install

mkdir -p "$PREFIX/dist"
cp "$PREFIX"/bin/ffmpeg.exe "$PREFIX"/bin/ffprobe.exe "$PREFIX/dist/"
if [ "$MODE" = shared ]; then
    cp "$PREFIX"/bin/*.dll "$PREFIX/dist/"
fi
strip --strip-all "$PREFIX"/dist/*

echo "configure: $(cat "$WORK/configure-command.txt")"
ls -l "$PREFIX/dist"
