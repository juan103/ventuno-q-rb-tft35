# Joy-IT RB-TFT3.5 on the Arduino VENTUNO Q

Scripts and device-tree sources for running a Joy-IT **RB-TFT3.5** (3.5" 480×320 SPI display,
ILI9486 panel behind shift registers, XPT2046 resistive touch) on the 40-pin JHAT header of an
Arduino **VENTUNO Q**, from the Linux side of the board.

There are two independent ways to drive it:

| | `tft.py` (userspace) | `kernel-driver/` + `fbshow.py` |
|---|---|---|
| Needs root | no | yes (once, to install) |
| Changes the system | nothing | replaces the boot device tree |
| Full-screen update | about 13 s | about 0.28 s (3.6 fps) |
| Result | a script that pushes pixels | a normal Linux framebuffer, `/dev/fb0` |

Start with `tft.py`: it proves the wiring without touching the system.

> **Warning.** The kernel-driver install overwrites `combined-dtb.dtb` on the board's `dtb_a`
> partition, the file Qualcomm's firmware boots from. It worked on the one board it was tested on.
> If the firmware rejects the file on yours, the board will not start Linux and you will have to
> reflash it with Arduino's recovery tooling. Read the scripts before running them. No warranty.

## Tested on

One VENTUNO Q (ABX00181), November 2026:

- Ubuntu 24.04.5, kernel `6.8.0-1089-qcom`, `arduino-app-cli` 0.13.0
- device tree model `Qualcomm Technologies, Inc. Monaco Monza addons` (`arduino,monza`)
- display plugged directly onto JHAT pins 1–26

Not tested: other kernel versions, behaviour across a reboot after `keep-desktop-off.sh`, the
`--kernel-touch` variant (it builds, it has never been booted), and touch with a real finger press
(the touch chip answers on SPI; nobody pressed the panel during testing).

## Pin mapping

From the [official full pinout](https://docs.arduino.cc/resources/pinouts/ABX00181-full-pinout.pdf), page 4.
"SoC GPIO" is the line number on `/dev/gpiochip2` (`f100000.pinctrl`).

| Display signal | JHAT pin | SoC GPIO | Note |
|---|---|---|---|
| MOSI | 19 | 26 | SPI controller `spi@98c000` (`spi3`, Linux `spi0`) |
| MISO | 21 | 25 | only the touch chip drives it; the display is write-only |
| SCK | 23 | 27 | |
| LCD_CS | 24 | 28 | |
| TP_CS | 26 | 88 | |
| LCD_RS (data/command) | 18 | 106 | |
| RST | 22 | 107 | |
| TP_IRQ | 11 | 85 | **shared with the Bluetooth UART flow-control line** |

## Option 1: `tft.py`, no root

Bit-bangs SPI through the GPIO character device. The default `arduino` user is in the `gpiod`
group, so this works on a stock image. Needs Python 3 and Pillow, both already on the board.

```bash
adb push tft.py /home/arduino/
adb shell "python3 ~/tft.py probe"          # reads the touch chip: checks the wiring
adb shell "python3 ~/tft.py demo --rot180"  # colour bars and text, about 13 s
```

Other commands: `fill RRGGBB`, `image FILE`, `text "message"`, `touch [seconds]`. Drop `--rot180`
if the picture is upside down for you.

`tft.py` stops working once the kernel driver is installed, because the kernel then owns the pins.

## Option 2: kernel driver

### Why it is done this way

- Qualcomm's firmware loads the device tree from `combined-dtb.dtb` on the `dtb_a` partition. That
  file is a plain concatenation of the device trees of many boards; the firmware picks one by
  board id.
- The kernel is built without `CONFIG_OF_OVERLAY`, so overlays cannot be loaded at runtime.

So `build.sh` applies an overlay to this board's tree at build time (`fdtoverlay`), and
`combine.py` swaps that one entry inside the combined file. Every other entry stays byte-identical.

The overlay ([`tft35.dts`](kernel-driver/tft35.dts)) adds to the JHAT SPI controller:

- GPIO chip selects on 28 and 88
- `display@0`, compatible `waveshare,rpi-lcd-35`, bound by the in-tree `ili9486` DRM driver
- `spidev@1` for the touch chip

Only `waveshare,rpi-lcd-35` is listed as compatible on purpose: adding `ilitek,ili9486` also
matches the staging `fb_ili9486` driver, which would compete for the device.

### Install

The board needs internet access for the build: `build.sh` downloads the Ubuntu
`device-tree-compiler` package and unpacks it locally (it is not installed).

```bash
adb push kernel-driver /home/arduino/
adb shell "cd ~/kernel-driver && bash build.sh"
adb shell -t "sudo bash /home/arduino/kernel-driver/install.sh && sudo reboot"
```

`install.sh` refuses to run if the kernel version, the stock device tree, or the file currently on
`dtb_a` is not what it was built against. It keeps a backup in `/var/backups/rb-tft35/`, writes
through a temporary name, and reads the file back before reporting success.

After the reboot you should have `/dev/fb0` (`ili9486drmfb`, 480×320) and `/dev/spidev0.1`.

### Keep the desktop off the display

Any display server treats the new device as a monitor. On the test board the first-boot notice
and then the GDM login screen took it over, which blocks drawing through `/dev/fb0`.

```bash
adb shell -t "sudo bash /home/arduino/kernel-driver/keep-desktop-off.sh"
```

This adds a udev rule that moves the display out of `seat0` (to `seat-tft`) and removes its
`master-of-seat` tag. X.org and GNOME only use displays of their own seat. GNOME's
`mutter-device-ignore` tag on its own was not enough: when GDM fell back to X.org, X.org ignored
the tag and took the display. The script restarts GDM once.

If the board still shows Arduino's first-boot notice, confirm it with a mouse or keyboard, or pass
`--confirm-notice`, which removes the same marker file the on-screen button removes.

### Draw

```bash
adb push fbshow.py /home/arduino/
adb shell "python3 ~/fbshow.py demo"
adb shell "python3 ~/fbshow.py text 'Hello' 'second line'"
```

Other commands: `info`, `image FILE`, `fill RRGGBB`, `touch [seconds]`. From your own Python code,
import the module and call `fbshow.blit(fbshow.find_fb(), pil_image)`.

### Keep each update under 64 kB

Writing the whole framebuffer in one go loses frames on this board. Measured with updates of
different heights, 30 updates each, at `spi-max-frequency` 16 MHz:

| Rows updated | Bytes on the wire | Timeouts |
|---|---|---|
| 16 | 15 kB | 0 / 30 |
| 32 | 30 kB | 0 / 30 |
| 64 | 60 kB | 0 / 30 |
| 68 | 63.8 kB | 0 / 30 |
| 72 | 67.5 kB | 3 / 30 |
| 100 | 93.8 kB | 2 / 30 |
| 160 | 150 kB | 0 / 30 |
| 320 (full screen) | 300 kB | 2 / 30 |

A timed-out update is logged as `ili9486 spi0.0: SPI transfer timed out` and is simply dropped.
Drawing 41 full frames back to back in single writes lost 5 of them.

The boundary matches 64 kB, and the kernel logs
`geni_spi 98c000.spi: Doing FIFO, cannot handle tx_nents-5` for large transfers. The likely
explanation is that a buffer that fits in one 64 kB DMA segment is sent by DMA, and anything larger
falls back to the SPI driver's FIFO path, which stalls. That part is inferred from the log message
and the size boundary, not traced in the driver.

`fbshow.blit()` therefore sends the screen in bands of 64 rows and waits for each band to finish
before writing the next. Result: 150 full frames, 0 timeouts, 3.6 frames per second.

### Touch

The default variant exposes the XPT2046 as `/dev/spidev0.1` for polling
(`fbshow.py touch 20` prints readings while you press).

A normal Linux input device needs the chip's interrupt line, which on this board is the Bluetooth
UART's flow-control pin. [`tft35-touch.dts`](kernel-driver/tft35-touch.dts) wires up the kernel
`ads7846` driver that way; install it with `install.sh --kernel-touch`. Expect Bluetooth to stop
working. This variant is untested.

### Undo

```bash
adb shell -t "sudo bash /home/arduino/kernel-driver/uninstall.sh && sudo reboot"
```

Puts the kernel package's stock `combined-dtb.dtb` back and removes both udev rules.

## Known limits

- **Kernel updates undo the install.** The image's own hook (`/etc/kernel/postinst.d/zzz-update-dtb`)
  copies the stock file onto `dtb_a` whenever a kernel is installed. Run `build.sh` and
  `install.sh` again afterwards.
- **The display becomes `card0`.** The board's own HDMI/DP controller moves to `card1`. Anything
  that hardcodes `/dev/dri/card0` will get the TFT.
- **Bluetooth and JHAT pin 11.** The touch interrupt pin is physically connected to the Bluetooth
  flow-control line whether or not you use it.
- **Speed.** 3.6 full frames per second through `fbshow.py`. Partial updates are proportionally
  faster.

## Files

| File | Purpose |
|---|---|
| `tft.py` | userspace driver, no root, GPIO bit-bang |
| `fbshow.py` | drawing through `/dev/fb0` in 64-row bands, touch polling through spidev |
| `kernel-driver/tft35.dts` | overlay: display + spidev touch |
| `kernel-driver/tft35-touch.dts` | overlay: display + kernel touch driver (untested) |
| `kernel-driver/build.sh` | builds both patched device trees into `out/` |
| `kernel-driver/combine.py` | replaces one entry of `combined-dtb.dtb` |
| `kernel-driver/install.sh` | checks, backs up, writes `dtb_a`, adds the spidev udev rule |
| `kernel-driver/keep-desktop-off.sh` | seat rule so X.org / GNOME leave the display alone |
| `kernel-driver/uninstall.sh` | restores the stock device tree, removes the rules |
