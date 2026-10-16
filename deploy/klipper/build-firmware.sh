#!/usr/bin/env bash
# Rebuild firmware.bin for the SKR Mini E3 V2 from the commit in KLIPPER_COMMIT.
#
# Only needed when moving Klipper to a new commit: change KLIPPER_COMMIT, run
# this, flash the new firmware.bin from an SD card (deploy/README.md), check the
# planter homes and waters, then commit both files together. The test
# tests/test_firmware_pin.py fails until they match.
#
# Needs Linux with: git make gcc-arm-none-eabi binutils-arm-none-eabi
# libnewlib-arm-none-eabi python3 (a Pi or WSL both work).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
COMMIT=$(tr -d '[:space:]' <"$HERE/KLIPPER_COMMIT")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

git init -q "$WORK/klipper"
git -C "$WORK/klipper" fetch -q --depth 1 https://github.com/Klipper3d/klipper.git "$COMMIT"
git -C "$WORK/klipper" checkout -q FETCH_HEAD

grep -v '^#' "$HERE/skr-mini-e3-v2.config" >"$WORK/klipper/.config"
make -C "$WORK/klipper" olddefconfig >/dev/null
make -C "$WORK/klipper" -j"$(nproc)" >/dev/null

cp "$WORK/klipper/out/klipper.bin" "$HERE/firmware.bin"
echo "Built $HERE/firmware.bin from Klipper $(git -C "$WORK/klipper" rev-parse --short HEAD)"
