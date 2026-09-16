# -*- coding: utf-8 -*-
"""生成 8 张图片测试样本（用 PIL + Windows 中文字体绘制，内容即 ground truth）。"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

IMG_DIR = Path(__file__).resolve().parent / 'images'

FONT_CANDIDATES = [
    (r'C:\Windows\Fonts\msyh.ttc', 0),
    (r'C:\Windows\Fonts\msyhbd.ttc', 0),
    (r'C:\Windows\Fonts\simhei.ttf', None),
    (r'C:\Windows\Fonts\simsun.ttc', 0),
]


def font(size):
    for path, idx in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size, index=idx) if idx is not None else ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


BG = (255, 255, 255)
FG = (33, 37, 41)
ACCENT = (11, 87, 208)
LINE = (200, 205, 212)
MUTED = (108, 117, 125)


def new_canvas(w, h, bg=BG):
    img = Image.new('RGB', (w, h), bg)
    return img, ImageDraw.Draw(img)


def table(d, x, y, headers, rows, widths, row_h=46, f_head=None, f_cell=None):
    f_head = f_head or font(24)
    f_cell = f_cell or font(23)
    # header
    d.rectangle([x, y, x + sum(widths), y + row_h], fill=(240, 243, 247))
    cx = x
    for i, htxt in enumerate(headers):
        d.text((cx + 14, y + 11), htxt, font=f_head, fill=FG)
        cx += widths[i]
    d.line([x, y + row_h, x + sum(widths), y + row_h], fill=LINE, width=2)
    cy = y + row_h
    for r in rows:
        cx = x
        for i, cell in enumerate(r):
            d.text((cx + 14, cy + 11), str(cell), font=f_cell, fill=FG)
            cx += widths[i]
        cy += row_h
        d.line([x, cy, x + sum(widths), cy], fill=(230, 234, 238), width=1)
    d.rectangle([x, y, x + sum(widths), cy], outline=LINE, width=2)
    return cy


def title(d, x, y, text, size=34, color=FG):
    d.text((x, y), text, font=font(size), fill=color)


def make_all():
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    # --- TC-101 商品库存表格截图 -------------------------------------------
    img, d = new_canvas(1000, 420)
    d.rectangle([0, 0, 1000, 74], fill=(11, 87, 208))
    title(d, 28, 18, 'Mysteel 钢材周度库存', 30, (255, 255, 255))
    title(d, 720, 22, '2026-09-11', 26, (222, 232, 255))
    table(d, 40, 116, ['品种', '本周库存', '周环比'], [
        ['螺纹钢社会库存', '512.34 万吨', '-12.5 万吨'],
        ['螺纹钢厂库', '198.60 万吨', '+3.2 万吨'],
    ], [300, 300, 300])
    title(d, 40, 350, '数据来源：Mysteel 周报', 20, MUTED)
    img.save(IMG_DIR / 'tc101_inventory_table.png')

    # --- TC-102 微信群聊截图 ------------------------------------------------
    img, d = new_canvas(760, 460, (237, 237, 237))
    d.rectangle([0, 0, 760, 66], fill=(60, 63, 65))
    title(d, 24, 18, '期货交流群 (48)', 26, (255, 255, 255))
    bubbles = [
        ('张伟', '螺纹社库这周 512.34 万吨，比上周少了 12.5 万吨。', 96),
        ('李娜', '螺纹厂库 198.6 万吨，周环比增加 3.2 万吨。', 236),
    ]
    for name, text, y in bubbles:
        d.text((32, y), name, font=font(19), fill=MUTED)
        d.rounded_rectangle([28, y + 28, 700, y + 100], radius=12, fill=(255, 255, 255))
        d.text((48, y + 48), text, font=font(22), fill=FG)
    img.save(IMG_DIR / 'tc102_chat.png')

    # --- TC-103 宏观数据发布截图 ---------------------------------------------
    img, d = new_canvas(1000, 420)
    d.rectangle([0, 0, 1000, 74], fill=(157, 34, 53))
    title(d, 28, 18, '国家统计局 · 价格指数发布', 30, (255, 255, 255))
    title(d, 740, 22, '2026年8月', 26, (255, 224, 228))
    table(d, 40, 116, ['指标', '同比', '环比'], [
        ['居民消费价格指数 (CPI)', '+0.6%', '+0.2%'],
        ['工业生产者出厂价格指数 (PPI)', '-1.8%', '-0.1%'],
    ], [420, 240, 240])
    title(d, 40, 350, '发布日期：2026-09-09', 20, MUTED)
    img.save(IMG_DIR / 'tc103_macro.png')

    # --- TC-104 行情价格截图 -------------------------------------------------
    img, d = new_canvas(900, 380)
    d.rectangle([0, 0, 900, 74], fill=(19, 34, 60))
    title(d, 28, 18, '长江有色金属网 · 现货报价', 28, (255, 255, 255))
    title(d, 40, 106, '电池级碳酸锂', 30, FG)
    d.text((40, 160), '73,500', font=font(64), fill=(198, 40, 40))
    d.text((250, 196), '元/吨', font=font(26), fill=FG)
    d.text((40, 250), '较前一交易日  -500 元/吨', font=font(25), fill=(198, 40, 40))
    title(d, 40, 312, '报价日期：2026-09-14', 21, MUTED)
    img.save(IMG_DIR / 'tc104_price.png')

    # --- TC-105 低质量模糊截图 ------------------------------------------------
    src = Image.open(IMG_DIR / 'tc101_inventory_table.png')
    src.resize((520, 218)).resize((1000, 420)).filter(ImageFilter.GaussianBlur(2.6)).save(
        IMG_DIR / 'tc105_blur.png')

    # --- TC-106 手机拍照倾斜 --------------------------------------------------
    Image.open(IMG_DIR / 'tc104_price.png').rotate(-11, expand=True, fillcolor=(250, 250, 250)).save(
        IMG_DIR / 'tc106_rotated.png')

    # --- TC-107 非金融图片（风景） --------------------------------------------
    img, d = new_canvas(900, 500)
    for i in range(500):
        d.line([(0, i), (900, i)], fill=(120 + i // 8, 170 + i // 10, 225))
    d.polygon([(0, 500), (300, 230), (560, 500)], fill=(96, 122, 82))
    d.polygon([(420, 500), (700, 200), (900, 500)], fill=(70, 96, 62))
    d.ellipse([640, 60, 760, 180], fill=(255, 214, 102))
    img.save(IMG_DIR / 'tc107_noise.png')

    # --- TC-108 多指标综合日报表格 --------------------------------------------
    img, d = new_canvas(1120, 560)
    d.rectangle([0, 0, 1120, 78], fill=(0, 82, 96))
    title(d, 30, 18, '【大宗商品 & 宏观 日报】', 32, (255, 255, 255))
    title(d, 830, 24, '2026-09-14', 26, (214, 240, 245))
    table(d, 40, 120, ['指标', '数值', '单位', '环比'], [
        ['螺纹钢社会库存 (09-11)', '512.34', '万吨', '-12.5'],
        ['螺纹钢厂库 (09-11)', '198.60', '万吨', '+3.2'],
        ['秦皇岛港煤炭库存', '612.00', '万吨', '-8.0'],
        ['电池级碳酸锂价格', '73500', '元/吨', '-500'],
    ], [400, 180, 160, 160])
    title(d, 40, 480, '编制：投研数据组', 20, MUTED)
    img.save(IMG_DIR / 'tc108_daily_report.png')

    return sorted(p.name for p in IMG_DIR.glob('*.png'))


if __name__ == '__main__':
    names = make_all()
    print('generated:', names)
    sys.exit(0)
