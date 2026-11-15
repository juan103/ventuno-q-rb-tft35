#!/usr/bin/env python3
"""Fast drawing on the RB-TFT3.5 once the kernel display driver is installed (uses /dev/fbN).

  fbshow.py info              show which framebuffer is the TFT
  fbshow.py demo              colour bars + text
  fbshow.py image FILE        show an image (scaled to fit)
  fbshow.py text "line" ...   show text lines
  fbshow.py fill RRGGBB       one colour
  fbshow.py touch [seconds]   print touch readings (needs /dev/spidev0.1)
Add --rot180 to flip the picture.
"""
import ctypes
import fcntl
import glob
import os
import struct
import sys
import time


def find_fb():
    best = None
    for d in sorted(glob.glob('/sys/class/graphics/fb[0-9]*')):
        name = open(d + '/name').read().strip()
        w, h = map(int, open(d + '/virtual_size').read().strip().split(','))
        bpp = int(open(d + '/bits_per_pixel').read())
        stride = int(open(d + '/stride').read())
        info = dict(dev='/dev/' + os.path.basename(d), name=name, w=w, h=h, bpp=bpp, stride=stride)
        if 'ili9486' in name or (w, h) in ((480, 320), (320, 480)):
            return info
        best = best or info
    return best


SPI_STATS = '/sys/class/spi_master/spi0/statistics/bytes_tx'
BAND_BYTES_ON_WIRE = 64 * 1024   # see blit()
_bus_probe = None


def _bytes_tx():
    try:
        with open(SPI_STATS) as f:
            return int(f.read())
    except OSError:
        return None


def _wait_band_sent(before, wire_bytes):
    """Block until the kernel has finished sending the band that was just written."""
    global _bus_probe
    nominal = wire_bytes * 8 / 16e6
    if before is None:
        time.sleep(nominal + 0.02); return
    end = time.time() + 0.5
    while _bytes_tx() - before < wire_bytes and time.time() < end:   # transfer has started
        time.sleep(0.0005)
    if _bus_probe is None:
        try:
            _bus_probe = Touch()
        except OSError:
            _bus_probe = False
    if _bus_probe:
        _bus_probe.read(0x90)        # same SPI bus: returns only when the display transfer is done
    else:
        time.sleep(nominal + 0.005)


def blit(fb, img, rot180=False, y0=0):
    """Show a PIL image on the TFT. `img` narrower/shorter than the screen is placed at row y0.

    The screen is sent in horizontal bands, one at a time. Reason (measured on this board,
    kernel 6.8.0-1089-qcom): the Qualcomm SPI driver sends transfers up to 64 kB by DMA, which
    is reliable, but larger ones through its FIFO path, which stalls and times out on a large
    share of full-screen updates. A band of 64 rows is 61 kB on the wire (RGB565).
    """
    from PIL import Image
    img = img.convert('RGB')
    if img.size[0] != fb['w'] or img.size[1] > fb['h']:
        img = img.resize((fb['w'], fb['h']), Image.LANCZOS)
    if rot180:
        img = img.rotate(180)
    h = img.size[1]
    if fb['bpp'] == 16:
        raw = img.tobytes()
        out = bytearray()
        pad = bytes(fb['stride'] - fb['w'] * 2)
        for i in range(0, len(raw), 3 * fb['w']):
            row = bytearray(fb['w'] * 2)
            for x in range(fb['w']):
                r, g, b = raw[i + 3 * x], raw[i + 3 * x + 1], raw[i + 3 * x + 2]
                v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                row[2 * x] = v & 255; row[2 * x + 1] = v >> 8
            out += row + pad
        out = bytes(out)
    else:  # 32 bpp XRGB8888, little endian = B G R X
        out = img.tobytes('raw', 'BGRX')
    stride = fb['stride']
    rows = max(1, BAND_BYTES_ON_WIRE // (fb['w'] * 2) - 4)     # 64 rows on a 480-wide panel
    fd = os.open(fb['dev'], os.O_RDWR)
    try:
        for y in range(0, h, rows):
            n = min(rows, h - y)
            before = _bytes_tx()
            os.pwrite(fd, out[y * stride:(y + n) * stride], (y0 + y) * stride)
            _wait_band_sent(before, fb['w'] * n * 2)
    finally:
        os.close(fd)


def demo_image(w, h):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new('RGB', (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    bars = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
            (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0)]
    bw = w // 8
    for i, c in enumerate(bars):
        d.rectangle([i * bw, 0, i * bw + bw - 1, 119], fill=c)
    d.rectangle([0, 0, w - 1, h - 1], outline=(255, 255, 255))
    d.text((20, 135), 'Kernel driver works', font=ImageFont.load_default(size=44), fill=(255, 255, 255))
    d.text((20, 195), time.strftime('drawn %H:%M:%S via /dev/fb'), font=ImageFont.load_default(size=28), fill=(0, 220, 255))
    d.text((20, 240), 'red / green / blue:', font=ImageFont.load_default(size=22), fill=(200, 200, 200))
    for i, c in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        d.rectangle([250 + i * 70, 236, 250 + i * 70 + 55, 270], fill=c)
    return img


class Touch:
    SPI_IOC_MESSAGE_1 = 0x40206B00

    def __init__(self, dev='/dev/spidev0.1'):
        self.fd = os.open(dev, os.O_RDWR)

    def read(self, command):
        tx = ctypes.create_string_buffer(bytes((command, 0, 0)), 3)
        rx = ctypes.create_string_buffer(3)
        xfer = struct.pack('<QQIIHBBBBBB', ctypes.addressof(tx), ctypes.addressof(rx),
                           3, 1000000, 0, 8, 0, 0, 0, 0, 0)
        fcntl.ioctl(self.fd, self.SPI_IOC_MESSAGE_1, xfer)
        return ((rx.raw[1] << 8 | rx.raw[2]) >> 3) & 0xFFF

    def sample(self):
        z1, z2 = self.read(0xB1), self.read(0xC1)
        x, y = self.read(0xD1), self.read(0x91)
        self.read(0x90)
        return x, y, z1, z2


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    rot = '--rot180' in sys.argv
    if not args:
        print(__doc__); return
    op = args[0]
    if op == 'touch':
        t = Touch()
        print('temp channel (sanity):', t.read(0x87), flush=True)
        end = time.time() + float(args[1] if len(args) > 1 else 15)
        print('touch the screen...', flush=True)
        while time.time() < end:
            x, y, z1, z2 = t.sample()
            if z1 > 100:
                print('  touch x=%4d y=%4d pressure=%4d' % (x, y, z1), flush=True)
            time.sleep(0.03)
        return
    fb = find_fb()
    if not fb:
        sys.exit('no framebuffer found - is the kernel driver installed?')
    if op == 'info':
        print(fb); return
    from PIL import Image, ImageDraw, ImageFont
    t0 = time.time()
    if op == 'demo':
        img = demo_image(fb['w'], fb['h'])
    elif op == 'image':
        img = Image.open(args[1])
    elif op == 'fill':
        c = int(args[1], 16)
        img = Image.new('RGB', (fb['w'], fb['h']), (c >> 16, (c >> 8) & 255, c & 255))
    elif op == 'text':
        img = Image.new('RGB', (fb['w'], fb['h']), (0, 0, 40))
        d = ImageDraw.Draw(img)
        for i, line in enumerate(args[1:]):
            d.text((20, 20 + i * 54), line, font=ImageFont.load_default(size=40), fill=(255, 255, 255))
    else:
        print(__doc__); return
    blit(fb, img, rot)
    print('drawn on %s (%s) in %.2f s' % (fb['dev'], fb['name'], time.time() - t0))


if __name__ == '__main__':
    main()
