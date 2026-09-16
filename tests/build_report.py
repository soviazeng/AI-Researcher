# -*- coding: utf-8 -*-
"""读取 tests/results/results_<label>.json，产出 Markdown 测试报告 + Excel 明细。

支持合并多个结果集：--labels unit,live --label final
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tests' / 'results'

DIM_LABEL = {
    'api_contract': '接口契约', 'record_count': '记录数量', 'record_match': '记录匹配',
    'indicator_mapping': '指标映射', 'value': '数值解析', 'unit': '单位处理',
    'date': '日期处理', 'change': '变化量解析', 'status': '状态与置信度',
    'warnings': '告警生成', 'anti_hallucination': '防幻觉', 'environment': '外部依赖',
}
CAT_LABEL = {'text_extraction': '文本抽取（LLM）', 'image_extraction': '图片抽取（Vision）',
             'api_contract': '接口契约（非 LLM）', 'unit': '确定性单元测试'}
SEV_ORDER = ['P0', 'P1', 'P2']
GREEN, RED, AMBER = '1E7B34', 'B02A2A', '9A6A00'


def load(labels):
    merged, meta = [], {}
    for lb in labels:
        p = OUT / f'results_{lb}.json'
        if not p.exists():
            raise SystemExit(f'找不到 {p}，先运行对应执行器')
        d = json.loads(p.read_text(encoding='utf-8'))
        merged.extend(d['results'])
        if not meta or d['summary'].get('dependency_ok') is not None:
            meta = d['summary']
    return {'summary': meta, 'results': merged}


def stats(results):
    runnable = [r for r in results if r['status'] != 'BLOCKED']
    s = {'total': len(results), 'blocked': len(results) - len(runnable), 'runnable': len(runnable)}
    s['pass'] = sum(1 for r in runnable if r['status'] == 'PASS')
    s['fail'] = sum(1 for r in runnable if r['status'] == 'FAIL')
    s['err'] = sum(1 for r in runnable if r['status'] == 'ERROR')
    s['rate'] = s['pass'] / s['runnable'] * 100 if s['runnable'] else 0
    all_a = [a for r in runnable for a in r['assertions']]
    s['a_total'] = len(all_a)
    s['a_pass'] = sum(1 for a in all_a if a['ok'])
    s['a_hard'] = sum(1 for a in all_a if a['hard'])
    s['a_hard_pass'] = sum(1 for a in all_a if a['hard'] and a['ok'])
    s['assert_rate'] = s['a_pass'] / s['a_total'] * 100 if s['a_total'] else 0
    s['hard_rate'] = s['a_hard_pass'] / s['a_hard'] * 100 if s['a_hard'] else 0
    return s


def by_key(results, keyfn):
    g = defaultdict(list)
    for r in results:
        g[keyfn(r)].append(r)
    return g


def dim_stats(results):
    g = defaultdict(lambda: [0, 0])
    for r in results:
        if r['status'] == 'BLOCKED':
            continue
        for a in r['assertions']:
            if a['dim'] == 'environment':
                continue
            g[a['dim']][1] += 1
            if a['ok']:
                g[a['dim']][0] += 1
    return g


def lat_stats(results):
    xs = sorted(r['latency_ms'] for r in results if r['status'] != 'BLOCKED' and r['latency_ms'])
    if not xs:
        return {}
    n = len(xs)
    return {'avg': sum(xs) / n, 'p50': xs[n // 2], 'p95': xs[min(n - 1, int(n * 0.95))],
            'max': xs[-1], 'total': sum(xs)}


def build_md(data, extra):
    res = data['results']
    meta = data['summary']
    s = stats(res)
    L = []
    A = L.append

    A('# 投研非结构化数据智能采集与标准化 Agent V1.1 —— 测试报告')
    A('')
    A('- **被测对象**：`E:\\各场景代码\\financial_data_agent_v1_1`（FastAPI，version 1.1.0）')
    A(f"- **测试时间**：{meta.get('generated_at')}")
    A(f"- **LLM 后端**：DeepSeek Responses API `{meta.get('model')}`")
    dep_ok = meta.get('dependency_ok', False)
    A(f"- **外部依赖状态**：{'可用' if dep_ok else '**不可用 —— ' + str(meta.get('dependency_reason')) + '**'}")
    A('- **测试方式**：确定性单元层（纯函数，无网络） + 真实启动 uvicorn 的 HTTP 端到端')
    A(f"- **用例规模**：{s['total']} 条，其中确定性单元用例 {len([r for r in res if r['category']=='unit'])} 条，"
      f"端到端用例 {len([r for r in res if r['category']!='unit'])} 条")
    A('')

    if not dep_ok:
        nblocked = len([r for r in res if r['status'] == 'BLOCKED'])
        A(f'> ⚠️ **本次运行存在环境阻塞**：{meta.get("dependency_reason")}。'
          f'{nblocked} 条依赖 LLM 的用例未能执行，已单列为「环境阻塞」且不计入通过率分母。'
          '下表反映的是**当前可执行部分**的真实结果；补齐依赖后重跑即可自动纳入。')
        A('')

    A('## 一、总体结论')
    A('')
    base_verdict = '**通过**' if s['rate'] >= 90 else ('**部分通过，存在需修复的问题**' if s['rate'] >= 60 else '**未通过**')
    if s['blocked']:
        verdict = (f"{base_verdict}（仅限可执行部分）—— 另有 {s['blocked']} 条 LLM 依赖用例因环境阻塞未受测，"
                   f"**在依赖补齐前不能对文本/图片抽取能力下结论**")
    else:
        verdict = base_verdict
    A(f"可执行用例通过率 **{s['rate']:.1f}%**（{s['pass']}/{s['runnable']}），判定：{verdict}。")
    A('')
    A('| 指标 | 数值 |')
    A('| --- | --- |')
    A(f"| 用例总数 | {s['total']} |")
    A(f"| 可执行 | {s['runnable']} |")
    A(f"| 通过 | {s['pass']} |")
    A(f"| 失败 | {s['fail']} |")
    A(f"| 异常（请求/服务错误） | {s['err']} |")
    A(f"| 环境阻塞（不计入分母） | {s['blocked']} |")
    A(f"| 可执行用例通过率 | **{s['rate']:.1f}%** |")
    A(f"| 断言总数（硬/软） | {s['a_total']}（{s['a_hard']} / {s['a_total']-s['a_hard']}） |")
    A(f"| 硬断言通过率 | **{s['hard_rate']:.1f}%**（{s['a_hard_pass']}/{s['a_hard']}） |")
    A(f"| 全部断言通过率 | {s['assert_rate']:.1f}%（{s['a_pass']}/{s['a_total']}） |")
    A('')

    A('## 二、分类与分级结果')
    A('')
    A('| 类别 | 用例 | 可执行 | 通过 | 通过率 | 硬断言通过率 |')
    A('| --- | --- | --- | --- | --- | --- |')
    for k, rs in by_key(res, lambda r: r['category']).items():
        st = stats(rs)
        if st['runnable'] == 0:
            A(f"| {CAT_LABEL.get(k,k)} | {st['total']} | 0 | 0 | — （全部环境阻塞） | — |")
            continue
        A(f"| {CAT_LABEL.get(k,k)} | {st['total']} | {st['runnable']} | {st['pass']} |"
          f" {st['rate']:.1f}% | {st['hard_rate']:.1f}% |")
    A('')
    A('| 级别 | 用例 | 可执行 | 通过 | 通过率 | 失败用例 |')
    A('| --- | --- | --- | --- | --- | --- |')
    for sev in SEV_ORDER:
        rs = [r for r in res if r['severity'] == sev]
        if not rs:
            continue
        st = stats(rs)
        bad = ', '.join(r['id'] for r in rs if r['status'] in ('FAIL', 'ERROR')) or '—'
        A(f"| {sev} | {st['total']} | {st['runnable']} | {st['pass']} | {st['rate']:.1f}% | {bad} |")
    A('')

    A('## 三、能力维度得分')
    A('')
    A('| 能力维度 | 断言数 | 通过 | 通过率 | 评级 |')
    A('| --- | --- | --- | --- | --- |')
    for dim, (ok, tot) in sorted(dim_stats(res).items(), key=lambda x: x[1][0] / x[1][1] if x[1][1] else 1):
        rate = ok / tot * 100 if tot else 0
        grade = 'A' if rate >= 95 else 'B' if rate >= 85 else 'C' if rate >= 70 else 'D' if rate >= 50 else 'E'
        A(f"| {DIM_LABEL.get(dim,dim)} | {tot} | {ok} | {rate:.1f}% | {grade} |")
    A('')

    ls = lat_stats(res)
    if ls:
        A('## 四、性能')
        A('')
        A('| 指标 | 值 |')
        A('| --- | --- |')
        A(f"| 平均单条耗时 | {ls['avg']/1000:.2f} s |")
        A(f"| P50 | {ls['p50']/1000:.2f} s |")
        A(f"| P95 | {ls['p95']/1000:.2f} s |")
        A(f"| 最大 | {ls['max']/1000:.2f} s |")
        A(f"| 总耗时 | {ls['total']/1000:.1f} s |")
        A('')

    blocked = [r for r in res if r['status'] == 'BLOCKED']
    if blocked:
        A('## 五、环境阻塞清单（未执行）')
        A('')
        A(f'共 {len(blocked)} 条，原因：**{meta.get("dependency_reason")}**。补齐后重跑即可自动纳入统计。')
        A('')
        A('| 用例 | 类别 | 级别 | 标题 |')
        A('| --- | --- | --- | --- |')
        for r in blocked:
            A(f"| {r['id']} | {CAT_LABEL.get(r['category'],r['category'])} | {r['severity']} | {r['title']} |")
        A('')

    A('## 六、失败用例明细')
    A('')
    bad = [r for r in res if r['status'] in ('FAIL', 'ERROR')]
    if not bad:
        A('无失败用例。')
    else:
        A(f'共 {len(bad)} 条。')
        A('')
        for r in bad:
            A(f"### {r['id']} · {r['title']}  `{r['severity']}`  →  **{r['status']}**")
            A('')
            A(f"- 类别：{CAT_LABEL.get(r['category'], r['category'])}；HTTP {r['http_status']}；"
              f"返回记录 {r['n_records']}；耗时 {r['latency_ms']/1000:.2f}s")
            A(f"- 硬断言：{r['hard_pass']}/{r['hard_total']}；软断言：{r['soft_pass']}/{r['soft_total']}")
            if r['error']:
                A(f"- 异常：`{r['error']}`")
            bad_a = [a for a in r['assertions'] if not a['ok'] and a['hard']]
            soft_a = [a for a in r['assertions'] if not a['ok'] and not a['hard']]
            if bad_a:
                A('')
                A('| 维度 | 断言 | 期望 | 实际 |')
                A('| --- | --- | --- | --- |')
                for a in bad_a[:14]:
                    exp = str(a['expected'])[:70].replace('|', '\\|')
                    act = str(a['actual'])[:70].replace('|', '\\|')
                    A(f"| {DIM_LABEL.get(a['dim'],a['dim'])} | {a['field']} | `{exp}` | `{act}` |")
            if soft_a:
                A('')
                A('未达标的软断言（提示项）：')
                for a in soft_a[:8]:
                    A(f"- {DIM_LABEL.get(a['dim'],a['dim'])} · {a['field']}："
                      f"期望 `{str(a['expected'])[:60]}`，实际 `{str(a['actual'])[:60]}`"
                      + (f"（{a['note']}）" if a.get('note') else ''))
            A('')

    A('## 七、问题清单与修复建议')
    A('')
    A(extra.get('findings_md', '（无）'))
    A('')

    A('## 八、附录 · 用例执行汇总')
    A('')
    A('| 用例 | 类别 | 级别 | 标题 | 结果 | HTTP | 记录 | 硬断言 | 耗时(s) |')
    A('| --- | --- | --- | --- | --- | --- | --- | --- | --- |')
    for r in res:
        icon = {'PASS': '通过', 'FAIL': '失败', 'ERROR': '异常', 'BLOCKED': '环境阻塞'}[r['status']]
        A(f"| {r['id']} | {CAT_LABEL.get(r['category'],r['category'])} | {r['severity']} | {r['title']} |"
          f" {icon} | {r['http_status']} | {r['n_records']} | {r['hard_pass']}/{r['hard_total']} |"
          f" {r['latency_ms']/1000:.2f} |")
    A('')
    return '\n'.join(L)


# --------------------------------------------------------------------------- excel

THIN = Side(style='thin', color='D0D5DD')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
H_FILL = PatternFill('solid', fgColor='1F3864')
H_FONT = Font(color='FFFFFF', bold=True, size=11)
OK_FILL = PatternFill('solid', fgColor='DCF2E3')
BAD_FILL = PatternFill('solid', fgColor='FBE0E0')
ERR_FILL = PatternFill('solid', fgColor='FFF3D6')
BLK_FILL = PatternFill('solid', fgColor='EAECF0')
STATUS_COLOR = {'PASS': GREEN, 'FAIL': RED, 'ERROR': AMBER, 'BLOCKED': '667085'}
STATUS_FILL = {'PASS': OK_FILL, 'FAIL': BAD_FILL, 'ERROR': ERR_FILL, 'BLOCKED': BLK_FILL}


def style_header(ws, row=1, ncol=None):
    ncol = ncol or ws.max_column
    for c in range(1, ncol + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill, cell.font = H_FILL, H_FONT
        cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def autosize(ws, caps=None):
    caps = caps or {}
    for i, col in enumerate(ws.iter_cols(), 1):
        width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[get_column_letter(i)].width = min(caps.get(i, 44), max(10, width + 3))


def build_xlsx(data, path, extra):
    res = data['results']
    meta = data['summary']
    s = stats(res)
    wb = Workbook()

    ws = wb.active
    ws.title = '1-总览'
    rows = [
        ['测试对象', 'financial_data_agent_v1_1（投研非结构化数据智能采集与标准化 Agent）'],
        ['版本', '1.1.0'],
        ['测试时间', meta.get('generated_at')],
        ['LLM 后端', f"DeepSeek Responses API / {meta.get('model')}"],
        ['外部依赖状态', '可用' if meta.get('dependency_ok') else f"不可用：{meta.get('dependency_reason')}"],
        ['用例总数', s['total']],
        ['可执行', s['runnable']],
        ['通过', s['pass']],
        ['失败', s['fail']],
        ['异常', s['err']],
        ['环境阻塞（不计入分母）', s['blocked']],
        ['可执行用例通过率', f"{s['rate']:.1f}%"],
        ['断言总数', s['a_total']],
        ['硬断言数', s['a_hard']],
        ['硬断言通过率', f"{s['hard_rate']:.1f}%"],
        ['全部断言通过率', f"{s['assert_rate']:.1f}%"],
    ]
    ws.append(['项目', '值'])
    for r in rows:
        ws.append(r)
    style_header(ws)
    for i in range(2, ws.max_row + 1):
        ws.cell(row=i, column=1).font = Font(bold=True)
        for c in (1, 2):
            ws.cell(row=i, column=c).border = BORDER
        ws.cell(row=i, column=2).alignment = Alignment(wrap_text=True, vertical='center')
    ws.column_dimensions['A'].width = 24
    ws.column_dimensions['B'].width = 76

    ws2 = wb.create_sheet('2-分类统计')
    ws2.append(['统计口径', '分组', '用例数', '可执行', '通过', '通过率'])
    for k, rs in by_key(res, lambda r: r['category']).items():
        st = stats(rs)
        ws2.append(['类别', CAT_LABEL.get(k, k), st['total'], st['runnable'], st['pass'],
                    '—（全部阻塞）' if st['runnable'] == 0 else f"{st['rate']:.1f}%"])
    for sev in SEV_ORDER:
        rs = [r for r in res if r['severity'] == sev]
        if rs:
            st = stats(rs)
            ws2.append(['严重级别', sev, st['total'], st['runnable'], st['pass'], f"{st['rate']:.1f}%"])
    for dim, (ok, tot) in sorted(dim_stats(res).items(), key=lambda x: x[1][0] / x[1][1] if x[1][1] else 1):
        ws2.append(['能力维度', DIM_LABEL.get(dim, dim), tot, tot, ok, f"{ok/tot*100:.1f}%"])
    ls = lat_stats(res)
    if ls:
        ws2.append([])
        for k, v in (('平均耗时(s)', ls['avg']), ('P50(s)', ls['p50']),
                     ('P95(s)', ls['p95']), ('最大耗时(s)', ls['max'])):
            ws2.append(['性能', k, round(v / 1000, 2)])
    style_header(ws2)
    autosize(ws2)

    ws3 = wb.create_sheet('3-用例明细')
    ws3.append(['用例ID', '类别', '级别', '标题', '结果', 'HTTP', '返回记录数', '硬断言通过',
                '硬断言总数', '软断言通过', '软断言总数', '耗时(ms)', '输入摘要', '异常/阻塞原因'])
    for r in res:
        ws3.append([r['id'], CAT_LABEL.get(r['category'], r['category']), r['severity'], r['title'],
                    r['status'], r['http_status'], r['n_records'], r['hard_pass'], r['hard_total'],
                    r['soft_pass'], r['soft_total'], r['latency_ms'],
                    str(r['input'])[:160], r['error'] or ''])
    style_header(ws3)
    for i in range(2, ws3.max_row + 1):
        st = ws3.cell(row=i, column=5).value
        fill = STATUS_FILL.get(st)
        for c in range(1, ws3.max_column + 1):
            ws3.cell(row=i, column=c).border = BORDER
            ws3.cell(row=i, column=c).alignment = Alignment(vertical='top', wrap_text=(c in (13, 14)))
            if fill:
                ws3.cell(row=i, column=c).fill = fill
        ws3.cell(row=i, column=5).font = Font(bold=True, color=STATUS_COLOR.get(st, '000000'))
    autosize(ws3, {4: 40, 13: 46, 14: 40})

    ws4 = wb.create_sheet('4-断言明细')
    ws4.append(['用例ID', '用例结果', '维度', '断言字段', '断言类型', '期望', '实际', '是否通过', '备注'])
    for r in res:
        if r['status'] == 'BLOCKED':
            continue
        for a in r['assertions']:
            ws4.append([r['id'], r['status'], DIM_LABEL.get(a['dim'], a['dim']), a['field'],
                        '硬' if a['hard'] else '软', str(a['expected'])[:200], str(a['actual'])[:200],
                        '通过' if a['ok'] else '不通过', a.get('note', '')])
    style_header(ws4)
    for i in range(2, ws4.max_row + 1):
        ok = ws4.cell(row=i, column=8).value == '通过'
        for c in range(1, ws4.max_column + 1):
            ws4.cell(row=i, column=c).border = BORDER
            ws4.cell(row=i, column=c).alignment = Alignment(vertical='top', wrap_text=(c in (6, 7)))
            if not ok:
                ws4.cell(row=i, column=c).fill = BAD_FILL
        ws4.cell(row=i, column=8).font = Font(bold=True, color=GREEN if ok else RED)
    autosize(ws4, {6: 40, 7: 40, 4: 30})

    ws5 = wb.create_sheet('5-失败清单')
    ws5.append(['用例ID', '级别', '标题', '失败维度', '失败断言数', '关键偏差'])
    for r in res:
        if r['status'] == 'PASS':
            continue
        bad_a = [a for a in r['assertions'] if not a['ok'] and a['hard']]
        dims = '、'.join(sorted({DIM_LABEL.get(a['dim'], a['dim']) for a in bad_a})) or \
               ('外部依赖' if r['status'] == 'BLOCKED' else '—')
        sample = ('；'.join(f"{a['field']}: 期望{a['expected']} 实际{a['actual']}" for a in bad_a[:3]))[:300]
        ws5.append([r['id'], r['severity'], r['title'], dims, len(bad_a), sample or (r['error'] or '')])
    style_header(ws5)
    for i in range(2, ws5.max_row + 1):
        for c in range(1, ws5.max_column + 1):
            ws5.cell(row=i, column=c).border = BORDER
            ws5.cell(row=i, column=c).alignment = Alignment(vertical='top', wrap_text=(c == 6))
    autosize(ws5, {3: 34, 6: 70})

    ws6 = wb.create_sheet('6-问题与建议')
    ws6.append(['编号', '严重度', '问题', '证据 / 现象', '影响', '修复建议', '归属'])
    for row in extra.get('findings_rows', []):
        ws6.append(row)
    style_header(ws6)
    for i in range(2, ws6.max_row + 1):
        for c in range(1, ws6.max_column + 1):
            ws6.cell(row=i, column=c).border = BORDER
            ws6.cell(row=i, column=c).alignment = Alignment(vertical='top', wrap_text=True)
    for i, w in enumerate([8, 10, 30, 42, 30, 46, 14], 1):
        ws6.column_dimensions[get_column_letter(i)].width = w

    wb.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--labels', default='live', help='逗号分隔，可合并多个结果集，如 unit,live')
    ap.add_argument('--label', default=None, help='输出文件名标签，默认取第一个 labels')
    args = ap.parse_args()
    labels = [x.strip() for x in args.labels.split(',') if x.strip()]
    label = args.label or '_'.join(labels)
    data = load(labels)
    extra_p = OUT / f'findings_{labels[-1]}.json'
    extra = json.loads(extra_p.read_text(encoding='utf-8')) if extra_p.exists() else {}
    md = OUT / f'report_{label}.md'
    xlsx = OUT / f'report_{label}.xlsx'
    md.write_text(build_md(data, extra), encoding='utf-8')
    build_xlsx(data, xlsx, extra)
    print('生成:', md)
    print('生成:', xlsx)


if __name__ == '__main__':
    main()
