#!/usr/bin/env bash
# Measure how much memory a cold frontend install and build take on this Pi.
#
# The open question for the Pi 3 A+ (512 MB) in ROADMAP.md: the 371 MB peak
# was taken warm on a Pi 4, with node_modules populated and npm's cache primed.
# A factory first boot is cold. This clears both, then runs `npm install` and
# `npm run build` while sampling system-wide memory and swap, and prints the
# figures to record.
#
# Run it as pi with the planter running normally (Klipper, the API and nginx
# up), so the numbers include everything else that shares the RAM:
#
#   bash /opt/greenthumb/deploy/pi/measure-build-memory.sh
#
# Needs internet: a cold npm install downloads every package. The live site is
# left alone -- the build goes to a scratch folder, not frontend/dist.
set -euo pipefail

FRONTEND=/opt/greenthumb/frontend
OUT=$(mktemp -d /tmp/gt-measure.XXXXXX)
SAMPLES="$OUT/memory.log"

if [ "$(id -un)" = root ]; then
  echo "Run this as pi, not root, so it measures pi's npm cache." >&2
  exit 1
fi
if [ ! -x /usr/bin/time ]; then
  echo "Installing GNU time for the per-process peaks..."
  sudo apt install -y time
fi

echo "== Board"
tr -d '\0' < /proc/device-tree/model; echo
grep -E "MemTotal|SwapTotal" /proc/meminfo
echo "Architecture: $(uname -m)"
echo
echo "== Services (all should be active)"
for unit in klipper greenthumb-api nginx; do
  printf "  %-16s %s\n" "$unit" "$(systemctl is-active "$unit" || true)"
done
echo

# System-wide used memory and swap, in MB, every half second until stopped.
sample() {
  while :; do
    awk '/^MemTotal:/ {t=$2} /^MemAvailable:/ {a=$2}
         /^SwapTotal:/ {st=$2} /^SwapFree:/ {sf=$2}
         END {printf "%d %d\n", (t-a)/1024, (st-sf)/1024}' /proc/meminfo
    sleep 0.5
  done >> "$SAMPLES"
}

used_now() {
  awk '/^MemTotal:/ {t=$2} /^MemAvailable:/ {a=$2} END {printf "%d", (t-a)/1024}' /proc/meminfo
}

echo "== Going cold: removing node_modules and clearing npm's cache"
rm -rf "$FRONTEND/node_modules"
npm cache clean --force 2>/dev/null
BASELINE=$(used_now)
echo "Used before starting: ${BASELINE} MB"
echo

sample &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null || true' EXIT

cd "$FRONTEND"
STATUS=0
echo "== npm install (cold)"
/usr/bin/time -v -o "$OUT/install.time" npm install --no-audit --no-fund || STATUS=$?
if [ "$STATUS" -eq 0 ]; then
  echo
  echo "== npm run build"
  /usr/bin/time -v -o "$OUT/build.time" \
    npm run build -- --outDir "$OUT/dist" --emptyOutDir || STATUS=$?
fi

kill $SAMPLER 2>/dev/null || true
wait $SAMPLER 2>/dev/null || true

# npm install rewrites the lockfile for ARM; drop that churn as the installer
# does, so the next git pull still fast-forwards.
git -C /opt/greenthumb checkout -- frontend/package-lock.json 2>/dev/null || true

peak_rss() {
  [ -f "$1" ] || { echo "did not run"; return; }
  awk -F': ' '/Maximum resident set size/ {printf "%d MB", $2/1024}' "$1"
}
wall() {
  [ -f "$1" ] || { echo "-"; return; }
  awk -F': ' '/Elapsed \(wall clock\)/ {print $2}' "$1"
}

PEAK_USED=$(awk 'BEGIN {m=0} $1>m {m=$1} END {print m}' "$SAMPLES")
PEAK_SWAP=$(awk 'BEGIN {m=0} $2>m {m=$2} END {print m}' "$SAMPLES")
TOTAL=$(awk '/^MemTotal:/ {printf "%d", $2/1024}' /proc/meminfo)

echo
echo "================ Results ================"
printf "%-28s %s\n" "Board:" "$(tr -d '\0' < /proc/device-tree/model)"
printf "%-28s %s\n" "npm install wall time:" "$(wall "$OUT/install.time")"
printf "%-28s %s\n" "npm install peak RSS:" "$(peak_rss "$OUT/install.time")"
printf "%-28s %s\n" "npm run build wall time:" "$(wall "$OUT/build.time")"
printf "%-28s %s\n" "npm run build peak RSS:" "$(peak_rss "$OUT/build.time")"
printf "%-28s %s\n" "Used before starting:" "${BASELINE} MB"
printf "%-28s %s\n" "Peak system-wide used:" "${PEAK_USED} MB of ${TOTAL} MB"
printf "%-28s %s\n" "Peak swap used:" "${PEAK_SWAP} MB"
printf "%-28s %s\n" "Throttled flags:" "$(vcgencmd get_throttled 2>/dev/null || echo unavailable)"
if [ "$STATUS" -ne 0 ]; then
  echo "A step FAILED (exit $STATUS). Check the output above for an out-of-memory kill."
  echo "Kernel log: $(dmesg 2>/dev/null | grep -i -c 'out of memory' || true) OOM lines (sudo dmesg to read)."
fi
echo "Raw samples and timings kept in $OUT"
exit "$STATUS"
