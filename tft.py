#!/usr/bin/env python3
"""Userspace driver for the Joy-IT RB-TFT3.5 (ILI9486 + XPT2046) on the
Arduino VENTUNO Q 40-pin JHAT header.

No root, no kernel driver: it bit-bangs SPI through the GPIO character device
(/dev/gpiochip2, GPIO v2 uAPI). Slow (a full frame takes a while) but works on
a stock image.

JHAT pin -> SoC GPIO (from the ABX00181 full pinout, page 4):
  19 MOSI   -> 26      21 MISO  -> 25      23 SCK -> 27
  24 LCD_CS -> 28      26 TP_CS -> 88
  18 LCD_RS -> 106     22 RST   -> 107
  11 TP_IRQ -> 85  (shared with the Bluetooth UART, left untouched)

Usage:
  tft.py probe            read the touch controller (checks wiring), time the bus
  tft.py init             reset + initialise the panel
  tft.py fill RRGGBB      fill the screen with one colour
  tft.py demo             colour bars + text
  tft.py image FILE       show an image (scaled to 480x320)
  tft.py text "message"   show a text message
  tft.py touch [seconds]  print touch readings
Add --no-init to skip the panel reset, --rot180 to flip the picture.
"""
import fcntl
import os
import struct
import sys
import time

CHIP = '/dev/gpiochip2'
MOSI, SCK, LCD_CS, TP_CS, DC, RST, MISO = 26, 27, 28, 88, 106, 107, 25
OUT_LINES = [MOSI, SCK, LCD_CS, TP_CS, DC, RST]
B_MOSI, B_SCK, B_LCD_CS, B_TP_CS, B_DC, B_RST = (1 << i for i in range(6))

GPIO_V2_GET_LINE = 0xC250B407
GPIO_V2_LINE_GET_VALUES = 0xC010B40E
GPIO_V2_LINE_SET_VALUES = 0xC010B40F
FLAG_INPUT, FLAG_OUTPUT = 1 << 2, 1 << 3

W, H = 480, 320


def request_lines(chipfd, offsets, flags, values=0):
    n = len(offsets)
    offs = struct.pack('<64I', *(offsets + [0] * (64 - n)))
    consumer = b'claude-tft'.ljust(32, b'\0')
    attrs, nattrs = b'', 0
    if flags & FLAG_OUTPUT:
        attrs = struct.pack('<IIQQ', 2, 0, values, (1 << n) - 1)  # initial output values
        nattrs = 1
    cfg = struct.pack('<QI5I', flags, nattrs, 0, 0, 0, 0, 0) + attrs.ljust(240, b'\0')
    tail = struct.pack('<II5Ii', n, 0, 0, 0, 0, 0, 0, 0)
    buf = bytearray(offs + consumer + cfg + tail)
    assert len(buf) == 592
    fcntl.ioctl(chipfd, GPIO_V2_GET_LINE, buf)
    return struct.unpack_from('<i', buf, 588)[0]


class Bus:
    def __init__(self):
        chip = os.open(CHIP, os.O_RDWR)
        # idle: both chip selects high, DC high, RST high, clock and data low
        self.out = request_lines(chip, OUT_LINES, FLAG_OUTPUT,
                                 B_LCD_CS | B_TP_CS | B_DC | B_RST)
        self.inp = request_lines(chip, [MISO], FLAG_INPUT)
        os.close(chip)
        pk = struct.pack
        d0 = pk('<QQ', 0, B_MOSI | B_SCK)       # data 0, clock low
        d1 = pk('<QQ', B_MOSI, B_MOSI | B_SCK)  # data 1, clock low
        self.ck1 = pk('<QQ', B_SCK, B_SCK)      # clock high (slave samples)
        self.ck0 = pk('<QQ', 0, B_SCK)
        self.table = [tuple(x for bit in range(7, -1, -1)
                            for x in ((d1 if (b >> bit) & 1 else d0), self.ck1))
                      for b in range(256)]

    def set(self, bits, mask):
        fcntl.ioctl(self.out, GPIO_V2_LINE_SET_VALUES, struct.pack('<QQ', bits, mask))

    def miso(self):
        buf = bytearray(struct.pack('<QQ', 0, 1))
        fcntl.ioctl(self.inp, GPIO_V2_LINE_GET_VALUES, buf)
        return buf[0] & 1

    def write(self, data):
        io, fd, req, table = fcntl.ioctl, self.out, GPIO_V2_LINE_SET_VALUES, self.table
        for b in data:
            for v in table[b]:
                io(fd, req, v)
        io(fd, req, self.ck0)

    # ---- LCD (ILI9486 behind 16-bit shift registers: every word is 16 bits) ----
    def cmd(self, c, *params):
        self.set(0, B_DC | B_LCD_CS)
        self.write(bytes((0, c)))
        if params:
            self.set(B_DC, B_DC)
            self.write(bytes(x for p in params for x in (0, p)))
        self.set(B_DC | B_LCD_CS, B_DC | B_LCD_CS)

    def lcd_init(self, rot180=False):
        self.set(B_RST, B_RST); time.sleep(0.05)
        self.set(0, B_RST); time.sleep(0.1)
        self.set(B_RST, B_RST); time.sleep(0.2)
        self.cmd(0xB0, 0x00)                 # interface mode
        self.cmd(0x11); time.sleep(0.25)     # sleep out
        self.cmd(0x3A, 0x55)                 # 16 bit/pixel
        self.cmd(0xC2, 0x44)                 # power control 3
        self.cmd(0xC5, 0x00, 0x00, 0x00, 0x00)  # VCOM
        self.cmd(0xE0, 0x0F, 0x1F, 0x1C, 0x0C, 0x0F, 0x08, 0x48, 0x98,
                 0x37, 0x0A, 0x13, 0x04, 0x11, 0x0D, 0x00)
        self.cmd(0xE1, 0x0F, 0x32, 0x2E, 0x0B, 0x0D, 0x05, 0x47, 0x75,
                 0x37, 0x06, 0x10, 0x03, 0x24, 0x20, 0x00)
        self.cmd(0xE2, 0x0F, 0x32, 0x2E, 0x0B, 0x0D, 0x05, 0x47, 0x75,
                 0x37, 0x06, 0x10, 0x03, 0x24, 0x20, 0x00)
        self.cmd(0x36, 0xE8 if rot180 else 0x28)  # landscape, BGR panel
        self.cmd(0x29); time.sleep(0.1)      # display on

    def window(self, x0, y0, x1, y1):
        self.cmd(0x2A, x0 >> 8, x0 & 255, x1 >> 8, x1 & 255)
        self.cmd(0x2B, y0 >> 8, y0 & 255, y1 >> 8, y1 & 255)

    def pixels(self, data, progress=True):
        """data: RGB565 big-endian bytes for the current window."""
        self.set(0, B_DC | B_LCD_CS)
        self.write(bytes((0, 0x2C)))
        self.set(B_DC, B_DC)
        t0, n, step = time.time(), len(data), 32768
        for i in range(0, n, step):
            self.write(data[i:i + step])
            if progress:
                print('  %3d%%  %.0fs' % (min(100, 100 * (i + step) // n), time.time() - t0),
                      flush=True)
        self.set(B_LCD_CS, B_LCD_CS)

    def show(self, img):
        from PIL import Image
        img = img.convert('RGB')
        if img.size != (W, H):
            img = img.resize((W, H), Image.LANCZOS)
        raw = img.tobytes()
        out = bytearray(W * H * 2)
        j = 0
        for i in range(0, len(raw), 3):
            v = ((raw[i] & 0xF8) << 8) | ((raw[i + 1] & 0xFC) << 3) | (raw[i + 2] >> 3)
            out[j] = v >> 8; out[j + 1] = v & 255; j += 2
        self.window(0, 0, W - 1, H - 1)
        self.pixels(bytes(out))

    # ---- touch (XPT2046) ----
    def tp(self, command):
        self.set(0, B_TP_CS)
        self.write(bytes((command,)))
        v = 0
        for _ in range(16):
            v = (v << 1) | self.miso()
            fcntl.ioctl(self.out, GPIO_V2_LINE_SET_VALUES, self.ck1)
            fcntl.ioctl(self.out, GPIO_V2_LINE_SET_VALUES, self.ck0)
        self.set(B_TP_CS, B_TP_CS)
        return (v >> 3) & 0xFFF

    def touch_raw(self):
        z1, z2 = self.tp(0xB1), self.tp(0xC1)
        x, y = self.tp(0xD1), self.tp(0x91)
        self.tp(0x90)  # power down, re-enable PENIRQ
        return x, y, z1, z2


def text_image(lines, bg=(0, 0, 40), fg=(255, 255, 255)):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new('RGB', (W, H), bg)
    d = ImageDraw.Draw(img)
    y = 20
    for size, txt, colour in lines:
        f = ImageFont.load_default(size=size)
        d.text((20, y), txt, font=f, fill=colour or fg)
        y += int(size * 1.35)
    return img


def demo_image():
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new('RGB', (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    bars = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
            (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0)]
    for i, c in enumerate(bars):
        d.rectangle([i * 60, 0, i * 60 + 59, 119], fill=c)
    d.rectangle([0, 0, W - 1, H - 1], outline=(255, 255, 255))
    d.text((20, 135), 'Hello from Claude', font=ImageFont.load_default(size=44), fill=(255, 255, 255))
    d.text((20, 195), 'VENTUNO Q  +  RB-TFT3.5', font=ImageFont.load_default(size=28), fill=(0, 220, 255))
    d.text((20, 240), 'red / green / blue:', font=ImageFont.load_default(size=22), fill=(200, 200, 200))
    for i, c in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        d.rectangle([250 + i * 70, 236, 250 + i * 70 + 55, 270], fill=c)
    d.text((20, 282), 'top-left corner is up here ^  (tell me if not)', font=ImageFont.load_default(size=18), fill=(255, 200, 0))
    return img


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = {a for a in sys.argv[1:] if a.startswith('--')}
    if not args:
        print(__doc__); return
    op = args[0]
    bus = Bus()
    rot = '--rot180' in flags

    if op == 'probe':
        t0 = time.time()
        for _ in range(50000):
            fcntl.ioctl(bus.out, GPIO_V2_LINE_SET_VALUES, bus.ck0)
        dt = time.time() - t0
        print('gpio set: %.1f us each -> ~%.0f kbit/s, full frame ~%.0f s'
              % (dt / 50000 * 1e6, 50000 / dt / 2 / 1000, W * H * 16 * 2 * dt / 50000))
        for name, c in (('temp0', 0x87), ('temp1', 0xF7), ('vbat', 0xA7), ('aux', 0xE7),
                        ('z1', 0xB1), ('z2', 0xC1), ('x', 0xD1), ('y', 0x91)):
            print('  touch %-5s = %s' % (name, [bus.tp(c) for _ in range(4)]))
        bus.tp(0x90)
        print('  MISO idle level (no chip selected):', [bus.miso() for _ in range(4)])
        return

    if op == 'touch':
        end = time.time() + float(args[1] if len(args) > 1 else 15)
        print('touch the screen...', flush=True)
        while time.time() < end:
            x, y, z1, z2 = bus.touch_raw()
            if z1 > 100:
                print('  touch  x=%4d y=%4d  pressure z1=%4d z2=%4d' % (x, y, z1, z2), flush=True)
            time.sleep(0.05)
        return

    if '--no-init' not in flags:
        bus.lcd_init(rot)
        print('panel initialised', flush=True)
    if op == 'init':
        return
    if op == 'fill':
        c = int(args[1], 16)
        r, g, b = c >> 16, (c >> 8) & 255, c & 255
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        bus.window(0, 0, W - 1, H - 1)
        bus.pixels(bytes((v >> 8, v & 255)) * (W * H))
    elif op == 'demo':
        bus.show(demo_image())
    elif op == 'image':
        from PIL import Image
        bus.show(Image.open(args[1]))
    elif op == 'text':
        bus.show(text_image([(40, t, None) for t in args[1:]]))
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
