#!/bin/sh
# Eye-match the Innoview's white to the ASUS through the Innoview's own DDC RGB gains.
# The ASUS is never touched. The probe gives the direction (Innoview reads cooler); your eyes
# pick how far. Put one blank white window across both screens, then step through candidates.
#
#   innoview-tune.sh orig        original 6500K preset
#   innoview-tune.sh 0..4        User preset candidate (0 = neutral 50/50/50, 4 = full probe suggestion)
#   innoview-tune.sh rgb R G B   exact gains, 0-100
#   innoview-tune.sh bright N    hardware brightness, 0-100
#   innoview-tune.sh show        current values
set -eu
D="--name=Innoview"
# RGB gains only take effect in the User colour preset (0x14 = 11); the 6500K preset (5) ignores
# them while still reading back the written values.
set_rgb() {
  betterdisplaycli set $D --ddc --vcp=0x14 --value=11 >/dev/null
  betterdisplaycli set $D --ddc --vcp=0x16 --value="$1" >/dev/null
  betterdisplaycli set $D --ddc --vcp=0x18 --value="$2" >/dev/null
  betterdisplaycli set $D --ddc --vcp=0x1A --value="$3" >/dev/null
  echo "Innoview User preset, RGB gain $1/$2/$3"
}
case "${1:-show}" in
  orig) betterdisplaycli set $D --ddc --vcp=0x14 --value=5 >/dev/null; echo "Innoview 6500K preset (original)" ;;
  0) set_rgb 50 50 50 ;;   # User preset, neutral gains
  1) set_rgb 50 50 47 ;;
  2) set_rgb 49 50 43 ;;
  3) set_rgb 48 50 40 ;;
  4) set_rgb 47 50 36 ;;   # probe suggestion: R 0.938, G 1, B 0.718
  rgb) set_rgb "$2" "$3" "$4" ;;
  bright) betterdisplaycli set $D --ddc --vcp=0x10 --value="$2" >/dev/null; echo "Innoview brightness $2" ;;
  show)
    for v in 0x16 0x18 0x1A 0x10; do printf "%s=%s " "$v" "$(betterdisplaycli get $D --ddc --vcp=$v)"; done; echo ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
