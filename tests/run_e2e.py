# -*- coding: utf-8 -*-
"""financial_data_agent_v1_1 端到端测试执行器。

- 自动拉起 uvicorn（真实 HTTP，非 TestClient）
- 逐条执行 tests/test_cases.json 的 50 条用例
- 硬断言（hard）+ 软断言（soft）分级判定
- 结果落盘 tests/results/results.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# 执行器自身也要读 .env，否则预检看不到 Key，会把「余额不足」误报成「未配置 Key」
load_dotenv(ROOT / '.env')
TESTS = ROOT / 'tests'
DATA = TESTS / 'test_cases.json'
OUT_DIR = TESTS / 'results'
IMG_DIR = TESTS / 'images'
PY = ROOT / '.venv' / 'Scripts' / 'python.exe'
if not PY.exists():
    PY = Path(sys.executable)

# --------------------------------------------------------------------------- 工具


def norm_date(v):
    """把各种中文/连字符日期写法归一，便于比对。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ('null', 'none', 'nan'):
        return None
    s = (s.replace('年', '-').replace('月', '-').replace('日', '')
         .replace('/', '-').replace('.', '-').replace('_', '-'))
    s = re.sub(r'-+', '-', s).strip('-')
    parts = s.split('-')
    out = []
    for i, p in enumerate(parts):
        if not p.isdigit():
            return s
        out.append(p if i == 0 else p.zfill(2))
    return '-'.join(out)


def date_match(expected, actual):
    e, a = norm_date(expected), norm_date(actual)
    if e is None or a is None:
        return e == a
    if e == a:
        return True
    return a.startswith(e + '-') or e.startswith(a + '-')


def num_eq(a, b, tol):
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= float(tol)
    except (TypeError, ValueError):
        return False


def any_eq(actual, options):
    for o in options:
        if o is None:
            if actual is None:
                return True
        elif isinstance(o, str) and isinstance(actual, str):
            if o.strip() == actual.strip():
                return True
        elif actual == o:
            return True
    return False


class A:
    """一条断言。"""
    def __init__(self, dim, field, expected, actual, ok, hard=True, note=''):
        self.dim, self.field = dim, field
        self.expected, self.actual, self.ok = expected, actual, ok
        self.hard, self.note = hard, note

    def to_dict(self):
        return {'dim': self.dim, 'field': self.field, 'expected': self.expected,
                'actual': self.actual, 'ok': bool(self.ok), 'hard': bool(self.hard),
                'note': self.note}


# --------------------------------------------------------------------------- 判定

def match_records(expected_records, actual_records):
    """贪心匹配：期望记录 -> 实际记录，保证字段级差异可展示。"""
    remaining = list(range(len(actual_records)))
    pairs = []
    for exp in expected_records:
        best, best_score = None, -1
        for i in remaining:
            act = actual_records[i]
            s = 0
            if 'indicator_id' in exp:
                if act.get('indicator_id') == exp['indicator_id']:
                    s += 100
                elif act.get('indicator_id') is None and exp['indicator_id'] is None:
                    s += 100
            if exp.get('value') is not None and act.get('value') is not None \
                    and num_eq(act.get('value'), exp['value'], exp.get('value_tol', 0.01)):
                s += 50
            if s > best_score:
                best, best_score = i, s
        if best is not None:
            remaining.remove(best)
            pairs.append((exp, actual_records[best]))
        else:
            pairs.append((exp, None))
    return pairs


def judge_record(exp, act, idx, out):
    tag = f'记录[{idx}]'
    if act is None:
        out.append(A('record_match', tag, '存在匹配记录', '无', False))
        return
    out.append(A('record_match', f'{tag}.存在', True, True, True))

    if 'indicator_id' in exp:
        exp_id = exp['indicator_id']
        act_id = act.get('indicator_id')
        dim = 'anti_hallucination' if exp_id is None and exp.get('unit', 'x') is None else 'indicator_mapping'
        if exp_id is None:
            dim = 'anti_hallucination'
        out.append(A(dim, f'{tag}.indicator_id', exp_id, act_id, act_id == exp_id))

    if 'standard_indicator' in exp:
        out.append(A('indicator_mapping', f'{tag}.standard_indicator', exp['standard_indicator'],
                     act.get('standard_indicator'), act.get('standard_indicator') == exp['standard_indicator']))

    if 'category' in exp:
        out.append(A('indicator_mapping', f'{tag}.category', exp['category'], act.get('category'),
                     act.get('category') == exp['category'], hard=False))

    if 'value' in exp:
        v_opts = exp.get('value_options')
        if v_opts:
            ok = any_eq(act.get('value'), v_opts)
            shown = v_opts
        else:
            ok = num_eq(act.get('value'), exp['value'], exp.get('value_tol', 0.01))
            shown = exp['value']
        out.append(A('value', f'{tag}.value', shown, act.get('value'), ok))

    if 'unit' in exp or 'unit_must_not_be_null' in exp:
        u_opts = exp.get('unit_options')
        if u_opts:
            ok = any_eq(act.get('unit'), u_opts)
            shown = u_opts
        else:
            ok = act.get('unit') == exp.get('unit')
            shown = exp.get('unit')
        out.append(A('unit', f'{tag}.unit', shown, act.get('unit'), ok))

    if 'date' in exp:
        d_opts = exp.get('date_options')
        if d_opts:
            ok = any(date_match(o, act.get('date')) for o in d_opts)
            shown = d_opts
        else:
            ok = date_match(exp['date'], act.get('date'))
            shown = exp['date']
        dim = 'anti_hallucination' if exp.get('date') is None else 'date'
        out.append(A(dim, f'{tag}.date', shown, act.get('date'), ok))

    chg = act.get('change') or {}
    if 'change_type' in exp or 'change_type_options' in exp:
        opts = exp.get('change_type_options') or [exp.get('change_type')]
        ok = any_eq(chg.get('type'), opts)
        out.append(A('change', f'{tag}.change.type', opts, chg.get('type'), ok,
                     hard='change_type' in exp))

    if 'change_value' in exp:
        ok = num_eq(chg.get('value'), exp['change_value'], exp.get('change_tol', 0.01))
        out.append(A('change', f'{tag}.change.value', exp['change_value'], chg.get('value'), ok))

    if 'status' in exp:
        ok = act.get('status') == exp['status']
        out.append(A('status', f'{tag}.status', exp['status'], act.get('status'),
                     ok, hard=not exp.get('status_soft', False)))

    if 'confidence_min' in exp:
        c = act.get('confidence')
        out.append(A('status', f'{tag}.confidence', f'>={exp["confidence_min"]}', c,
                     c is not None and c >= exp['confidence_min'], hard=False))

    warns = act.get('warnings') or []
    for w in exp.get('expect_warnings_contains', []):
        ok = any(w in str(x) for x in warns)
        out.append(A('warnings', f'{tag}.warnings⊇"{w}"', w, warns, ok))

    if exp.get('if_unit_null_expect_warning') and act.get('unit') is None:
        w = exp['if_unit_null_expect_warning']
        ok = any(w in str(x) for x in warns)
        out.append(A('unit', f'{tag}.unit为空时告警"{w}"', w, warns, ok))

    if 'original_value_soft_contains' in exp:
        ov = str(act.get('original_value') or '')
        s = exp['original_value_soft_contains']
        out.append(A('value', f'{tag}.original_value⊇"{s}"', s, act.get('original_value'),
                     s in ov, hard=False))


def judge_case(case, status_code, body, error):
    out = []
    exp = case['expect']
    http_ok = status_code == exp.get('http_status')
    out.append(A('api_contract', 'http_status', exp.get('http_status'), status_code, http_ok))

    if error:
        return out

    for k, v in (exp.get('json_fields') or {}).items():
        actual = body.get(k) if isinstance(body, dict) else None
        out.append(A('api_contract', f'body.{k}', v, actual, actual == v))

    if not isinstance(body, dict):
        return out
    if 'records' not in body:
        return out

    records = body.get('records') or []
    n = len(records)
    out.append(A('record_count', 'records 数量', f'[{exp.get("min_records", 0)}, {exp.get("max_records", 99)}]',
                 n, exp.get('min_records', 0) <= n <= exp.get('max_records', 99)))

    ids = [r.get('indicator_id') for r in records if r.get('indicator_id')]
    for want in exp.get('expected_indicators', []):
        out.append(A('indicator_mapping', f'包含指标 {want}', want, ids, want in ids))
    for bad in exp.get('forbidden_indicators', []):
        out.append(A('anti_hallucination', f'不应出现指标 {bad}', f'不含 {bad}', ids, bad not in ids))

    for want_date in exp.get('distinct_dates', []):
        ok = any(date_match(want_date, r.get('date')) for r in records)
        out.append(A('date', f'含日期 {want_date}', want_date,
                     [r.get('date') for r in records], ok))

    if exp.get('min_records', 0) == 0 and exp.get('max_records', 0) == 0:
        out.append(A('anti_hallucination', '无金融数据时不得臆造记录', 0, n, n == 0))

    for i, (e, a) in enumerate(match_records(exp.get('records', []), records), 1):
        judge_record(e, a, i, out)

    for w in exp.get('expect_global_warnings_contains', []):
        gws = body.get('global_warnings') or []
        out.append(A('warnings', f'global_warnings⊇"{w}"', w, gws, any(w in str(x) for x in gws)))

    return out


# --------------------------------------------------------------------------- 请求

def build_request(case):
    req = case['request']
    endpoint = req['endpoint']
    method = req.get('method', 'POST').upper()
    text = req.get('text')
    if 'text_gen' in req:
        g = req['text_gen']
        text = '\n'.join([g['unit']] * g['repeat'])
    return endpoint, method, text, req


def send(client, case, base_url):
    req = case['request']
    endpoint, method, text, req = build_request(case)
    url = base_url + endpoint

    if method == 'GET':
        r = client.get(url)
        return r

    if endpoint == '/api/v1/extract/text':
        data = {}
        if not req.get('omit_text'):
            data['text'] = text if text is not None else ''
        if 'context' in req:
            data['context'] = req['context']
        return client.post(url, data=data)

    if endpoint == '/api/v1/extract/image':
        if req.get('omit_file'):
            return client.post(url, data={'context': req.get('context', '')})
        if req.get('gen_oversized'):
            payload = b'\x89PNG\r\n\x1a\n' + b'\x00' * (21 * 1024 * 1024)
            return client.post(url, files={'file': ('big.png', payload, 'image/png')})
        img = TESTS / req['image']
        ct = req.get('content_type', 'image/png')
        return client.post(url, files={'file': (img.name, img.read_bytes(), ct)})

    return client.request(method, url)


# --------------------------------------------------------------------------- 服务

def preflight():
    """用一次零成本调用判定外部依赖是否可用，返回 (ok, reason)。

    区分「环境阻塞」（无 Key / 余额不足 / 鉴权失败）与「功能缺陷」，
    避免把 402 之类的账户问题误记成被测代码的失败。
    """
    key = os.getenv('DEEPSEEK_API_KEY') or os.getenv('OPENAI_API_KEY')
    if not key:
        return False, '未配置 DEEPSEEK_API_KEY'
    base = os.getenv('OPENAI_BASE_URL') or os.getenv('DEEPSEEK_BASE_URL') or 'https://api.deepseek.com'
    try:
        r = httpx.get(base.rstrip('/') + '/user/balance',
                      headers={'Authorization': 'Bearer ' + key}, timeout=30)
        if r.status_code == 401:
            return False, 'API Key 无效（HTTP 401）'
        if r.status_code == 200:
            d = r.json()
            if not d.get('is_available'):
                b = (d.get('balance_infos') or [{}])[0]
                return False, (f"DeepSeek 账户不可用：余额 {b.get('total_balance')} "
                               f"{b.get('currency', '')}（HTTP 402 Insufficient Balance）")
            return True, 'ok'
        return True, f'balance 接口返回 HTTP {r.status_code}，继续执行'
    except Exception as exc:
        return True, f'预检跳过（{exc.__class__.__name__}），继续执行'


def is_llm_case(case):
    """只有“预期 200 成功抽取”的用例才真正依赖 LLM。

    诸如 TC-202/203/204/205 这类入参校验用例，在触达 Agent 之前就以 422/400 返回，
    与模型可用性无关，不应被环境预检标记为阻塞。
    """
    req = case['request']
    return (req['endpoint'].startswith('/api/v1/extract')
            and case['expect'].get('http_status') == 200)


def start_server(port):
    """拉起真实 uvicorn 服务。

    注意：日志必须重定向到文件，不能接 subprocess.PIPE ——
    管道缓冲区写满后 uvicorn 会阻塞在写日志上，导致整个服务假死
    （表现为请求端 180s 超时）。
    """
    env = dict(os.environ)
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUT_DIR / 'server.log'
    log = open(log_path, 'w', encoding='utf-8')
    proc = subprocess.Popen(
        [str(PY), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port), '--log-level', 'warning'],
        cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    proc._log_handle = log                                    # 保持引用，防止被 GC
    base = f'http://127.0.0.1:{port}'
    for _ in range(120):
        if proc.poll() is not None:
            log.flush()
            raise RuntimeError(f'服务启动失败，见 {log_path}:\n' +
                               log_path.read_text(encoding='utf-8', errors='replace')[-2000:])
        try:
            if httpx.get(base + '/health', timeout=2).status_code == 200:
                return proc, base
        except Exception:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError('服务启动超时')


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-url', default=None, help='复用已启动的服务')
    ap.add_argument('--port', type=int, default=8123)
    ap.add_argument('--only', default=None, help='只跑指定 id，逗号分隔')
    ap.add_argument('--label', default='live', help='结果文件名标签')
    args = ap.parse_args()

    cases = json.loads(DATA.read_text(encoding='utf-8'))['cases']
    if args.only:
        want = {x.strip() for x in args.only.split(',')}
        cases = [c for c in cases if c['id'] in want]

    key = os.getenv('DEEPSEEK_API_KEY') or os.getenv('OPENAI_API_KEY')
    dep_ok, dep_reason = preflight()
    proc, base = None, args.base_url
    if not base:
        proc, base = start_server(args.port)

    print(f'[{args.label}] base={base} 用例={len(cases)} '
          f'LLM={"ON" if key else "OFF"} 预检={"通过" if dep_ok else "阻塞"}'
          + ('' if dep_ok else f' → {dep_reason}'))

    results = []
    try:
        with httpx.Client(timeout=180.0) as client:
            for i, case in enumerate(cases, 1):
                # 环境阻塞：LLM 依赖用例直接标记 BLOCKED，不计入通过率分母
                if not dep_ok and is_llm_case(case):
                    results.append({
                        'id': case['id'], 'category': case['category'], 'severity': case['severity'],
                        'title': case['title'], 'status': 'BLOCKED',
                        'http_status': None, 'latency_ms': 0.0, 'n_records': None,
                        'hard_total': 0, 'hard_pass': 0, 'soft_total': 1, 'soft_pass': 0,
                        'assertions': [{'dim': 'environment', 'field': '外部依赖可用',
                                        'expected': '可用', 'actual': dep_reason,
                                        'ok': False, 'hard': False, 'note': '环境阻塞，非功能缺陷'}],
                        'input': case['request'].get('text') or case['request'].get('image')
                                 or case['request']['endpoint'],
                        'error': dep_reason, 'response': None,
                    })
                    print(f'  BLK  {case["id"]} {case["title"]}  (环境阻塞)')
                    continue

                t0 = time.perf_counter()
                code, body, err = None, None, None
                try:
                    r = send(client, case, base)
                    code = r.status_code
                    try:
                        body = r.json()
                    except Exception:
                        body = {'_raw': r.text[:500]}
                except Exception as exc:
                    err = f'{exc.__class__.__name__}: {exc}'
                dt = (time.perf_counter() - t0) * 1000

                asserts = judge_case(case, code, body, err)
                hard = [a for a in asserts if a.hard]
                soft = [a for a in asserts if not a.hard]
                hard_pass = sum(1 for a in hard if a.ok)
                status = 'ERROR' if err else ('PASS' if hard_pass == len(hard) else 'FAIL')

                results.append({
                    'id': case['id'], 'category': case['category'], 'severity': case['severity'],
                    'title': case['title'], 'status': status,
                    'http_status': code, 'latency_ms': round(dt, 1),
                    'n_records': len((body or {}).get('records') or []) if isinstance(body, dict) else None,
                    'hard_total': len(hard), 'hard_pass': hard_pass,
                    'soft_total': len(soft), 'soft_pass': sum(1 for a in soft if a.ok),
                    'assertions': [a.to_dict() for a in asserts],
                    'input': case['request'].get('text') or case['request'].get('image') or case['request']['endpoint'],
                    'error': err,
                    'response': body,
                })
                flag = {'PASS': 'OK  ', 'FAIL': 'FAIL', 'ERROR': 'ERR '}[status]
                print(f'  {flag} {case["id"]} {case["title"]}  ({dt/1000:.1f}s, hard {hard_pass}/{len(hard)})')
    finally:
        if proc:
            proc.kill()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f'results_{args.label}.json'
    runnable = [r for r in results if r['status'] != 'BLOCKED']
    summary = {
        'label': args.label, 'base_url': base, 'llm_enabled': bool(key) and dep_ok,
        'dependency_ok': dep_ok, 'dependency_reason': dep_reason,
        'model': os.getenv('OPENAI_MODEL', 'deepseek-flash'),
        'total': len(results), 'runnable': len(runnable),
        'blocked': sum(1 for r in results if r['status'] == 'BLOCKED'),
        'passed': sum(1 for r in runnable if r['status'] == 'PASS'),
        'failed': sum(1 for r in runnable if r['status'] == 'FAIL'),
        'errors': sum(1 for r in runnable if r['status'] == 'ERROR'),
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    out.write_text(json.dumps({'summary': summary, 'results': results}, ensure_ascii=False, indent=2),
                   encoding='utf-8')
    print(f'\n汇总: 可执行 {summary["runnable"]} 条 → 通过 {summary["passed"]}, '
          f'失败 {summary["failed"]}, 异常 {summary["errors"]}; '
          f'环境阻塞 {summary["blocked"]} 条')
    print(f'明细: {out}')


if __name__ == '__main__':
    main()
