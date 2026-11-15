#!/bin/bash
# Install the RB-TFT3.5 device tree on the VENTUNO Q.   Run on the board:  sudo bash install.sh
#   sudo bash install.sh                  display driver, touch chip on /dev/spidev0.1 (Bluetooth unaffected)
#   sudo bash install.sh --kernel-touch   display + kernel touch driver (takes the Bluetooth flow-control pin)
#
# What it changes:
#   * combined-dtb.dtb on the dtb_a partition (the file Qualcomm's firmware boots from)
#   * /etc/udev/rules.d/99-rb-tft35.rules (lets the gpiod group use /dev/spidev0.1)
#   * /var/backups/rb-tft35/ (copy of the file that was on the partition)
# Undo with:  sudo bash uninstall.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run this with sudo"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
VARIANT=tft35
[ "${1:-}" = "--kernel-touch" ] && VARIANT=tft35-touch
NEW=$HERE/out/combined-$VARIANT.dtb
KVER=$(cat "$HERE/out/kernel-version")
STOCK=/usr/lib/firmware/$KVER/device-tree/qcom/combined-dtb.dtb
DEV=/dev/disk/by-partlabel/dtb_a
BK=/var/backups/rb-tft35
die() { echo "ABORTED, nothing changed: $*"; exit 1; }

# ---- checks before touching anything ----
grep -qa 'arduino,monza' /proc/device-tree/compatible || die "this is not a VENTUNO Q"
[ "$(uname -r)" = "$KVER" ] || die "built for kernel $KVER but running $(uname -r); run build.sh again"
[ -b "$DEV" ] || die "$DEV not found"
( cd "$HERE/out" && sha256sum -c --quiet SHA256SUMS ) || die "build output is corrupt; run build.sh again"
cmp -s "$STOCK" "$HERE/out/combined-stock.dtb" || die "the kernel's stock device tree changed since the build; run build.sh again"
python3 "$HERE/combine.py" "$STOCK" "$HERE/out/base.dtb" "$HERE/out/$VARIANT-board.dtb" /tmp/rb-tft35-check.dtb >/dev/null
cmp -s /tmp/rb-tft35-check.dtb "$NEW" || die "rebuilt file does not match $NEW"
rm -f /tmp/rb-tft35-check.dtb

MNT=$(mktemp -d)
mount "$DEV" "$MNT"
trap 'mountpoint -q "$MNT" && umount "$MNT"; rmdir "$MNT" 2>/dev/null || true' EXIT
echo "dtb_a contents before:"; ls -la "$MNT"
CUR=$MNT/combined-dtb.dtb
[ -f "$CUR" ] || die "no combined-dtb.dtb on dtb_a"
if ! cmp -s "$CUR" "$STOCK" && ! cmp -s "$CUR" "$HERE/out/combined-tft35.dtb" \
   && ! cmp -s "$CUR" "$HERE/out/combined-tft35-touch.dtb"; then
  die "the file on dtb_a is neither the stock one nor one of ours; not overwriting something unknown"
fi
FREE=$(df --output=avail -k "$MNT" | tail -1)
[ "$FREE" -gt 16000 ] || die "not enough free space on dtb_a (${FREE} kB)"

# ---- backup, then write via a temporary name and rename ----
mkdir -p "$BK"
cp -n "$CUR" "$BK/combined-dtb.dtb.before-$(date +%Y%m%d-%H%M%S)"
cp "$NEW" "$MNT/combined-dtb.new"
sync
cmp "$MNT/combined-dtb.new" "$NEW"
mv -f "$MNT/combined-dtb.new" "$CUR"
sync
umount "$MNT"
# read it back from the partition after a fresh mount
mount -o ro "$DEV" "$MNT"
cmp "$CUR" "$NEW" || { echo "!!! VERIFY FAILED - run: sudo bash $HERE/uninstall.sh  BEFORE rebooting"; exit 2; }
echo "dtb_a contents after:"; ls -la "$MNT"
umount "$MNT"

cat > /etc/udev/rules.d/99-rb-tft35.rules <<'EOF'
# Joy-IT RB-TFT3.5 touch chip (XPT2046) on the JHAT header
SUBSYSTEM=="spidev", KERNEL=="spidev0.1", GROUP="gpiod", MODE="0660"
EOF
udevadm control --reload-rules || true

echo
echo "OK: installed variant '$VARIANT' (verified on the partition). Reboot to activate."
