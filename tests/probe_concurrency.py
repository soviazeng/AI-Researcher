# -*- coding: utf-8 -*-
"""并发探针：验证 async 路由中同步调用 LLM 是否会阻塞事件循环。

main.py 中 extract_text 是 `def`（FastAPI 放线程池，可并发），
extract_image 是 `async def` 却同步阻塞调用 LLM（占用事件循环，串行化）。

判据：N 个并发请求的总墙钟时间
  - 接近单次耗时 → 并发（OK）
  - 接近 N × 单次耗时 → 串行阻塞（问题）
"""
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8123'
N = int(sys.argv[2]) if len(sys.argv) > 2 else 3

TEXT = '2026年9月11日，螺纹钢社会库存512.34万吨，周环比减少12.5万吨。'
IMG = (ROOT / 'tests' / 'images' / 'tc101_inventory_table.png').read_bytes()


def one_text(i):
    t = time.perf_counter()
    with httpx.Client(timeout=180) as c:
        c.post(BASE + '/api/v1/extract/text', data={'text': TEXT})
    return time.perf_counter() - t


def one_image(i):
    t = time.perf_counter()
    with httpx.Client(timeout=180) as c:
        c.post(BASE + '/api/v1/extract/image',
               files={'file': ('t.png', IMG, 'image/png')})
    return time.perf_counter() - t


def probe(name, fn, n):
    t_serial = time.perf_counter()
    for i in range(n):
        fn(i)
    serial = time.perf_counter() - t_serial

    t_par = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n) as ex:
        list(ex.map(fn, range(n)))
    par = time.perf_counter() - t_par

    return {'interface': name, 'n': n,
            'single_avg_s': round(serial / n, 2),
            'serial_total_s': round(serial, 2),
            'parallel_total_s': round(par, 2),
            'speedup': round(serial / par, 2) if par else None,
            'verdict': '串行阻塞' if par > serial / n * 1.8 else '并发正常'}


def llm_live():
    """探测 LLM 后端是否真实可用，用于标注本次测量的可信度。"""
    key = os.getenv('DEEPSEEK_API_KEY') or os.getenv('OPENAI_API_KEY')
    if not key:
        return False
    base = os.getenv('DEEPSEEK_BASE_URL') or os.getenv('OPENAI_BASE_URL') or 'https://api.deepseek.com'
    try:
        d = httpx.get(base.rstrip('/') + '/user/balance',
                      headers={'Authorization': 'Bearer ' + key}, timeout=20).json()
        return bool(d.get('is_available'))
    except Exception:
        return False


def main():
    live = llm_live()
    out = []
    print(f'probe @ {BASE}  n={N}  LLM可用={live}')
    for name, fn in (('/api/v1/extract/text (sync def → 线程池)', one_text),
                     ('/api/v1/extract/image (async def → 事件循环)', one_image)):
        r = probe(name, fn, N)
        r['llm_live'] = live
        out.append(r)
        print(f"  {r['interface']}\n"
              f"    单次均值 {r['single_avg_s']}s | 串行总 {r['serial_total_s']}s | "
              f"并发总 {r['parallel_total_s']}s | 加速比 {r['speedup']}x → {r['verdict']}")
    p = ROOT / 'tests' / 'results' / 'concurrency_probe.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('saved:', p)


if __name__ == '__main__':
    main()
