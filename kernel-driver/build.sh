#!/bin/bash
# Build patched device trees for the RB-TFT3.5. Runs on the board as the normal user and changes
# nothing on the system: it only writes into ./out and ./tools. The standard dtc/fdtoverlay tools
# are not on the board image, so the Ubuntu package is downloaded and unpacked locally (not installed).
set -euo pipefail
cd "$(dirname "$0")"
KVER=${1:-$(uname -r)}
SRC=/usr/lib/firmware/$KVER/device-tree/qcom

if ! command -v dtc >/dev/null && [ ! -x tools/usr/bin/dtc ]; then
  mkdir -p tools/deb && ( cd tools/deb && apt-get download device-tree-compiler libfdt1 >/dev/null )
  for d in tools/deb/*.deb; do dpkg-deb -x "$d" tools; done
fi
if [ -x tools/usr/bin/dtc ]; then
  PATH="$PWD/tools/usr/bin:$PATH"
  export LD_LIBRARY_PATH="$PWD/tools/usr/lib/aarch64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
dtc --version

rm -rf out && mkdir -p out
cp "$SRC/monaco-addons-monza-ovl.dtb" out/base.dtb
cp "$SRC/combined-dtb.dtb" out/combined-stock.dtb
dtc -I dtb -O dts -o out/base.dts out/base.dtb 2>/dev/null
for v in tft35 tft35-touch; do
  dtc -@ -I dts -O dtb -o out/$v.dtbo $v.dts
  fdtoverlay -i out/base.dtb -o out/$v-board.dtb out/$v.dtbo
  dtc -I dtb -O dts -o out/$v-board.dts out/$v-board.dtb 2>out/$v-dtc-warnings.txt
  python3 combine.py out/combined-stock.dtb out/base.dtb out/$v-board.dtb out/combined-$v.dtb
done
echo "$KVER" > out/kernel-version
( cd out && sha256sum combined-stock.dtb combined-tft35.dtb combined-tft35-touch.dtb > SHA256SUMS && cat SHA256SUMS )
