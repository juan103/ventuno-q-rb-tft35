#!/bin/bash
# Put the stock device tree back (the same copy Arduino's own kernel hook installs).
# Run on the board:  sudo bash uninstall.sh   then reboot.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run this with sudo"; exit 1; }
# same rule as /etc/kernel/postinst.d/zzz-update-dtb: the kernel grub boots first
KVER=$(grep -m 1 "/boot/vmlinuz-" /boot/grub/grub.cfg | awk '{print $2}'); KVER=${KVER#/boot/vmlinuz-}
[ -n "$KVER" ] || KVER=$(uname -r)
STOCK=/usr/lib/firmware/$KVER/device-tree/qcom/combined-dtb.dtb
DEV=/dev/disk/by-partlabel/dtb_a
[ -f "$STOCK" ] || { echo "stock file $STOCK not found"; exit 1; }
MNT=$(mktemp -d)
mount "$DEV" "$MNT"
trap 'mountpoint -q "$MNT" && umount "$MNT"; rmdir "$MNT" 2>/dev/null || true' EXIT
cp "$STOCK" "$MNT/combined-dtb.new"
sync
cmp "$MNT/combined-dtb.new" "$STOCK"
mv -f "$MNT/combined-dtb.new" "$MNT/combined-dtb.dtb"
sync
umount "$MNT"
mount -o ro "$DEV" "$MNT"
cmp "$MNT/combined-dtb.dtb" "$STOCK"
umount "$MNT"
rm -f /etc/udev/rules.d/99-rb-tft35.rules /etc/udev/rules.d/62-rb-tft35-no-desktop.rules /etc/udev/rules.d/72-rb-tft35-no-desktop.rules
udevadm control --reload-rules || true
echo "OK: stock device tree for kernel $KVER restored. Reboot to activate."
