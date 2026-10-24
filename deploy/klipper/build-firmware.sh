#!/usr/bin/env bash
# Rebuild firmware.bin for each supported SKR board from the commit in
# KLIPPER_COMMIT.
#
# Each board has a folder here holding its build options (klipper.config) and
# the firmware built from them (firmware.bin), so the file copied to the SD
# card already has the name the bootloader wants:
#
#   skr-mini-e3-v2/   STM32F103, 28 KiB bootloader
#   skr-mini-e3-v3/   STM32G0B1, 8 KiB bootloader
#
#   ./build-firmware.sh                    # every board
#   ./build-firmware.sh skr-mini-e3-v3     # just one
#
# Only needed when moving Klipper to a new commit or adding a board: change
# KLIPPER_COMMIT, run this, flash the new firmware.bin from an SD card
# (deploy/README.md), check the planter homes and waters, then commit them
# together. tests/test_firmware_pin.py fails until every board's firmware.bin
# matches KLIPPER_COMMIT.
#
# Needs Linux with: git make gcc-arm-none-eabi binutils-arm-none-eabi
# libnewlib-arm-none-eabi python3 (a Pi or WSL both work).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
COMMIT=$(tr -d '[:space:]' <"$HERE/KLIPPER_COMMIT")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

if [ "$#" -gt 0 ]; then
  BOARDS=("$@")
else
  BOARDS=()
  for config in "$HERE"/*/klipper.config; do
    BOARDS+=("$(basename "$(dirname "$config")")")
  done
fi

git init -q "$WORK/klipper"
git -C "$WORK/klipper" fetch -q --depth 1 https://github.com/Klipper3d/klipper.git "$COMMIT"
git -C "$WORK/klipper" checkout -q FETCH_HEAD

for board in "${BOARDS[@]}"; do
  config="$HERE/$board/klipper.config"
  if [ ! -f "$config" ]; then
    echo "No build options for $board: expected $config" >&2
    exit 1
  fi
  rm -rf "$WORK/klipper/out" "$WORK/klipper/.config"
  grep -v '^#' "$config" >"$WORK/klipper/.config"
  make -C "$WORK/klipper" olddefconfig >/dev/null
  make -C "$WORK/klipper" -j"$(nproc)" >/dev/null
  cp "$WORK/klipper/out/klipper.bin" "$HERE/$board/firmware.bin"
  echo "Built $board/firmware.bin from Klipper $(git -C "$WORK/klipper" rev-parse --short HEAD)"
done
