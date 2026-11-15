#!/bin/bash
# Keep the Ubuntu login screen / desktop off the RB-TFT3.5 so your own programs can draw on /dev/fb0.
# Run on the board:
#   sudo bash keep-desktop-off.sh                    add the rule, restart the login screen
#   sudo bash keep-desktop-off.sh --confirm-notice   also acknowledge the first-boot notice
#
# How: the TFT is taken out of the desktop's seat (seat0). X.org and GNOME only use displays of
# their own seat, so neither touches it. (GNOME's own "ignore" tag is set too, but X.org does not
# honour that one, which is why the tag alone was not enough.)
#
# --confirm-notice does exactly what the on-screen "Confirm" button does: it removes
#   /var/lib/arduino-desktop-customization/distribution_terms_not_confirmed
#
# Changes: /etc/udev/rules.d/72-rb-tft35-no-desktop.rules  (removed again by uninstall.sh)
#          restarts gdm (the login screen) once so it lets go of the TFT
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run this with sudo"; exit 1; }
RULE=/etc/udev/rules.d/72-rb-tft35-no-desktop.rules
OLD_RULE=/etc/udev/rules.d/62-rb-tft35-no-desktop.rules
FLAG=/var/lib/arduino-desktop-customization/distribution_terms_not_confirmed
CARD=/dev/dri/by-path/platform-98c000.spi-cs-0-card

rm -f "$OLD_RULE"
cat > "$RULE" <<'EOF'
# Joy-IT RB-TFT3.5: not part of the desktop seat, so X.org / GNOME leave it alone and programs
# can draw on /dev/fb0. Must sort after 71-seat.rules (which adds master-of-seat).
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", DRIVERS=="ili9486", ENV{ID_SEAT}="seat-tft", TAG-="master-of-seat", TAG+="mutter-device-ignore"
SUBSYSTEM=="graphics", KERNEL=="fb[0-9]*", DRIVERS=="ili9486", ENV{ID_SEAT}="seat-tft"
EOF
udevadm control --reload-rules
udevadm trigger --action=change --subsystem-match=drm --subsystem-match=graphics
udevadm settle --timeout=10 || true

INFO=$(udevadm info "$CARD")
if echo "$INFO" | grep -q 'ID_SEAT=seat-tft' && ! echo "$INFO" | grep -q 'CURRENT_TAGS=.*master-of-seat'; then
  echo "OK: the TFT is no longer part of the desktop seat."
else
  echo "WARNING: the rule was written but did not take effect. Details:"
  echo "$INFO" | grep -E 'ID_SEAT|CURRENT_TAGS'
  exit 2
fi

if [ "${1:-}" = "--confirm-notice" ] && [ -f "$FLAG" ]; then
  rm -f "$FLAG"
  echo "OK: first-boot notice acknowledged."
elif [ -f "$FLAG" ]; then
  echo "The first-boot notice is still pending: press Confirm with a mouse or keyboard,"
  echo "or run this script again with --confirm-notice."
fi

echo "Restarting the login screen so it lets go of the TFT..."
systemctl restart gdm || echo "note: gdm restart reported an error; a reboot will do the same job"
echo "Done."
