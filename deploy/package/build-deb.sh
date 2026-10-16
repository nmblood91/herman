#!/usr/bin/env bash
# Build greenthumb_<version>_arm64.deb from this checkout.
#
# Runs on arm64 Debian Bookworm -- the CI container, or a Pi -- because the
# wheelhouse holds compiled wheels and they must match the planter's Python and
# CPU. The frontend has to be built first (frontend/dist); the planter never
# runs Node.
#
#   VERSION=0.2.0 deploy/package/build-deb.sh            -> dist/greenthumb_0.2.0_arm64.deb
#
# VERSION defaults to pyproject.toml's version plus ~local, which sorts below
# the release of the same number.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO"

PYPROJECT_VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
VERSION=${VERSION:-${PYPROJECT_VERSION}~local}
COMMIT=${COMMIT:-$(git rev-parse --short HEAD 2>/dev/null || echo unknown)}
KLIPPER_COMMIT=$(tr -d '[:space:]' <deploy/klipper/KLIPPER_COMMIT)

[ -f frontend/dist/index.html ] || { echo "Build the frontend first: cd frontend && npm ci && npm run build" >&2; exit 1; }
[ "$(dpkg --print-architecture)" = arm64 ] || { echo "Build on arm64 Debian (the wheels must match the Pi)" >&2; exit 1; }

BUILD=$REPO/build/deb
STAGE=$BUILD/root
APP=$STAGE/opt/greenthumb
rm -rf "$BUILD"
mkdir -p "$APP" "$STAGE/DEBIAN" "$REPO/dist"

# --- the application -------------------------------------------------------------

cp -r greenthumb "$APP/greenthumb"
find "$APP/greenthumb" -name __pycache__ -prune -exec rm -rf {} +
cp pyproject.toml requirements.txt "$APP/"
mkdir -p "$APP/frontend"
cp -r frontend/dist "$APP/frontend/dist"
mkdir -p "$APP/deploy/klipper" "$APP/deploy/package"
cp deploy/klipper/printer.cfg.example deploy/klipper/KLIPPER_COMMIT deploy/klipper/firmware.bin "$APP/deploy/klipper/"
install -m 0755 deploy/package/setup-system.sh "$APP/deploy/package/setup-system.sh"

# Marks this tree as an installed package (see greenthumb/paths.py) and says
# what it is, for the Software panel.
python3 - "$APP/BUILD_INFO.json" "$VERSION" "$COMMIT" "$KLIPPER_COMMIT" <<'PY'
import json, sys
from datetime import datetime, timezone
path, version, commit, klipper = sys.argv[1:]
json.dump({
    "version": version,
    "commit": commit,
    "klipper_commit": klipper,
    "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}, open(path, "w"), indent=2)
PY

# --- Klipper's host code, at exactly the firmware's commit -------------------------

KLIPPER_SRC=$BUILD/klipper-src
git init -q "$KLIPPER_SRC"
git -C "$KLIPPER_SRC" fetch -q --depth 1 https://github.com/Klipper3d/klipper.git "$KLIPPER_COMMIT"
git -C "$KLIPPER_SRC" checkout -q FETCH_HEAD
mkdir -p "$APP/klipper/scripts"
cp -r "$KLIPPER_SRC/klippy" "$APP/klipper/klippy"
cp "$KLIPPER_SRC/scripts/klippy-requirements.txt" "$APP/klipper/scripts/"
cp "$KLIPPER_SRC/COPYING" "$APP/klipper/COPYING"
find "$APP/klipper" -name __pycache__ -prune -exec rm -rf {} +
# No git checkout on the planter, so Klipper reads its version from here. The
# short hash matches what the firmware reports, so Klipper sees no mismatch.
git -C "$KLIPPER_SRC" rev-parse --short=7 HEAD >"$APP/klipper/klippy/.version"

# --- wheels for both virtualenvs ----------------------------------------------------

python3 -m venv "$BUILD/venv"
"$BUILD/venv/bin/pip" install --quiet --upgrade pip wheel
"$BUILD/venv/bin/pip" wheel --quiet -w "$APP/wheelhouse" -r requirements.txt
"$BUILD/venv/bin/pip" wheel --quiet -w "$APP/wheelhouse" -r "$APP/klipper/scripts/klippy-requirements.txt"

# --- system files --------------------------------------------------------------------

install -d "$STAGE/lib/systemd/system"
install -m 0644 deploy/systemd/*.service deploy/systemd/*.timer "$STAGE/lib/systemd/system/"
install -D -m 0644 deploy/nginx/greenthumb.conf "$STAGE/etc/nginx/sites-available/greenthumb.conf"
install -D -m 0440 deploy/package/sudoers "$STAGE/etc/sudoers.d/greenthumb"
install -D -m 0644 .env.example "$STAGE/etc/greenthumb/greenthumb.env"
install -D -m 0755 deploy/package/greenthumb-update "$STAGE/usr/lib/greenthumb/greenthumb-update"

# Settings the user may edit: an upgrade keeps their copy.
cat >"$STAGE/DEBIAN/conffiles" <<'EOF'
/etc/greenthumb/greenthumb.env
/etc/nginx/sites-available/greenthumb.conf
EOF

for script in postinst prerm postrm; do
  install -m 0755 "deploy/package/$script" "$STAGE/DEBIAN/$script"
done

# python3 pinned to 3.11 because the wheelhouse is built for it: Bookworm.
cat >"$STAGE/DEBIAN/control" <<EOF
Package: greenthumb
Version: $VERSION
Architecture: arm64
Maintainer: ${MAINTAINER:-GreenThumb}
Installed-Size: $(du -sk "$STAGE" | cut -f1)
Depends: python3 (>= 3.11), python3 (<< 3.12), python3-venv, nginx, i2c-tools, gcc, libc6-dev, libffi-dev, sudo
Section: misc
Priority: optional
Homepage: https://github.com/nmblood91/herman
Description: GreenThumb smart planter
 Waters, lights and monitors up to four plants on a gantry: the web UI,
 the API, and the Klipper host that drives the gantry and the pump.
EOF

visudo -c -f "$STAGE/etc/sudoers.d/greenthumb" >/dev/null

OUT=$REPO/dist/greenthumb_${VERSION}_arm64.deb
dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$OUT" >/dev/null
echo "$OUT"
