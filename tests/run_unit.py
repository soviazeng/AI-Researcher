# -*- coding: utf-8 -*-
"""确定性单元/集成测试层：不调用 LLM，验证知识库、后处理状态机、Schema 契约。

输出 tests/results/results_unit.json，结构与 run_e2e.py 完全一致，便于合并出报告。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.agent import FinancialDataAgent          # noqa: E402
from app.services.indicator_master import INDICATORS, all_indicators, resolve_candidates  # noqa: E402
from app.schemas import ExtractionResult, FinancialRecord  # noqa: E402

OUT = ROOT / 'tests' / 'results'


class Case:
    def __init__(self, cid, title, severity, dim_hint=''):
        self.id, self.title, self.severity, self.dim_hint = cid, title, severity, dim_hint
        self.asserts = []

    def check(self, dim, field, expected, actual, hard=True, note=''):
        ok = expected == actual if not isinstance(expected, tuple) else expected == actual
        self.asserts.append({'dim': dim, 'field': field, 'expected': expected,
                             'actual': actual, 'ok': bool(ok), 'hard': hard, 'note': note})
        return ok


def base_record(**kw):
    r = {'raw_indicator': '螺纹钢社会库存', 'indicator_id': None, 'standard_indicator': None,
         'category': None, 'date': '2026-09-11', 'value': 512.34, 'original_value': '512.34万吨',
         'unit': '万吨', 'frequency': None,
         'change': {'type': '周环比', 'value': -12.5, 'unit': '万吨'},
         'market': None, 'region': None, 'source': None, 'evidence': '螺纹钢社会库存512.34万吨',
         'confidence': 0.98, 'status': 'ready', 'warnings': [], 'candidates': []}
    r.update(kw)
    return r


def run():
    agent = FinancialDataAgent()
    cases = []

    # ---------- U-01 知识库：精确标准名 ----------
    c = Case('U-01', '知识库-标准名精确命中得 1.0', 'P0', 'indicator_mapping')
    for it in INDICATORS:
        cands = resolve_candidates(it['standard_name'])
        c.check('indicator_mapping', f"{it['standard_name']} 命中",
                (it['indicator_id'], 1.0),
                (cands[0]['indicator_id'] if cands else None,
                 cands[0]['score'] if cands else None))
    cases.append(c)

    # ---------- U-02 知识库：别名精确命中 ----------
    c = Case('U-02', '知识库-别名精确命中得 1.0', 'P0', 'indicator_mapping')
    for alias, want in [('RB库存', 'COMMODITY_REBAR_SOCIAL_INVENTORY'),
                        ('螺纹社库', 'COMMODITY_REBAR_SOCIAL_INVENTORY'),
                        ('秦港库存', 'COMMODITY_QHD_PORT_COAL_INVENTORY'),
                        ('锂价', 'COMMODITY_LITHIUM_CARBONATE_PRICE')]:
        cands = resolve_candidates(alias)
        c.check('indicator_mapping', f'别名 {alias}',
                (want, 1.0),
                (cands[0]['indicator_id'] if cands else None, cands[0]['score'] if cands else None))
    cases.append(c)

    # ---------- U-03 近似命中被挡在 0.95 自动回填线之外 ----------
    c = Case('U-03', '知识库-近似命中得分夹在 0.95 之下，无法触发自动回填', 'P1', 'indicator_mapping')
    # '螺纹库存'/'秦皇岛港库存' 本身在 aliases 里，属精确命中（U-02 已覆盖）；
    # 这里用“包含别名/标准名但不等价”的串，才会走到 indicator_master.py:25-26 的分支。
    alias_sub = ['螺纹钢库存数据', '秦港库存量']          # 别名是子串 → 享 0.88 保底
    name_sub = ['螺纹钢社会库存数据', '秦皇岛港煤炭库存情况']  # 仅标准名是子串 → 无保底
    for q in alias_sub + name_sub:
        cands = resolve_candidates(q)
        s = cands[0]['score'] if cands else None
        c.check('indicator_mapping', f'近似命中 {q} 得分<0.95（不触发自动回填）', True,
                s is not None and s < 0.95, note=f'实际 score={s}，自动回填阈值 0.95')
    for q in alias_sub:
        s = resolve_candidates(q)[0]['score']
        c.check('indicator_mapping', f'别名子串 {q} 享 0.88 保底', True, s >= 0.88,
                note=f'实际 score={s}')
    for q in name_sub:
        s = resolve_candidates(q)[0]['score']
        c.check('indicator_mapping', f'仅标准名子串 {q} 未享 0.88 保底（实现不一致）', True,
                s < 0.88, hard=False,
                note=f'实际 score={s}：indicator_master.py:25 只对 aliases 做子串判断，'
                     f'standard_name 是子串时不给保底，同类输入得分口径不统一（问题 F-08）')
    cases.append(c)

    # ---------- U-04 未知指标不召回 ----------
    c = Case('U-04', '知识库-完全无关输入返回空候选', 'P1', 'indicator_mapping')
    for q in ('完全不存在的指标XYZ', '上证指数', 'zxcvbnm'):
        c.check('indicator_mapping', f'未知“{q}”', [], resolve_candidates(q))
    cases.append(c)

    # ---------- U-05 易混淆口径的误召回风险 ----------
    c = Case('U-05', '知识库-易混淆口径仍返回候选（有误映射风险）', 'P0', 'anti_hallucination')
    cands = resolve_candidates('螺纹钢表观消费量')
    top = cands[0] if cands else None
    c.check('anti_hallucination', '“螺纹钢表观消费量”不应精确命中库存口径',
            True, bool(top) and top['score'] < 0.95,
            note=f'实际 top={top}')
    c.check('anti_hallucination', '候选得分 < 0.95（不触发自动回填）', True,
            bool(top) and top['score'] < 0.95, hard=False,
            note=f"score={top['score'] if top else None}")
    cases.append(c)

    # ---------- U-06 知识库字段完整性 ----------
    c = Case('U-06', '知识库-条目字段完整且主键唯一', 'P1', 'indicator_mapping')
    need = ['indicator_id', 'standard_name', 'category', 'aliases', 'default_unit', 'frequency']
    missing = [f"{i.get('indicator_id')}.{k}" for i in INDICATORS for k in need if k not in i]
    c.check('indicator_mapping', '字段缺失项', [], missing)
    ids = [i['indicator_id'] for i in INDICATORS]
    c.check('indicator_mapping', 'indicator_id 唯一', len(ids), len(set(ids)))
    c.check('indicator_mapping', '知识库规模', 6, len(INDICATORS), hard=False,
            note='覆盖度有限，期货/指数/个股等常见数据均超纲')
    cases.append(c)

    # ---------- U-07 post_process：未知 indicator_id 被清空 ----------
    # 注意：raw_indicator 必须本身也无法解析，否则会被 ≥0.95 的候选自动回填（U-08 场景）。
    c = Case('U-07', '后处理-幻觉指标 ID 被清空', 'P0', 'anti_hallucination')
    res = agent.post_process({'records': [base_record(raw_indicator='某虚构指标XYZ',
                                                      indicator_id='NOT_EXIST_ID',
                                                      standard_indicator='不存在指标',
                                                      category='乱写')],
                              'global_warnings': []}, 'text')
    r = res['records'][0]
    c.check('anti_hallucination', 'indicator_id', None, r['indicator_id'])
    c.check('anti_hallucination', 'standard_indicator', None, r['standard_indicator'])
    c.check('anti_hallucination', 'category', None, r['category'])
    cases.append(c)

    # ---------- U-08 post_process：自动回填（含 category 缺陷） ----------
    c = Case('U-08', '后处理-候选≥0.95 自动回填指标', 'P0', 'indicator_mapping')
    res = agent.post_process({'records': [base_record(indicator_id=None, raw_indicator='螺纹钢社会库存')],
                              'global_warnings': []}, 'text')
    r = res['records'][0]
    c.check('indicator_mapping', 'indicator_id 自动回填',
            'COMMODITY_REBAR_SOCIAL_INVENTORY', r['indicator_id'])
    c.check('indicator_mapping', 'standard_indicator 自动回填',
            '螺纹钢社会库存', r['standard_indicator'])
    # 缺陷证据：同类知识库字段未一并回填
    c.check('indicator_mapping', 'category 是否一并回填（当前实现未回填）',
            '商品/库存', r['category'], hard=False,
            note='缺陷 F-04：回填时漏写 category / frequency')
    c.check('indicator_mapping', 'frequency 是否一并回填（当前实现未回填）',
            'weekly', r['frequency'], hard=False, note='缺陷 F-04')
    cases.append(c)

    # ---------- U-09 post_process：缺字段强制 pending_review ----------
    c = Case('U-09', '后处理-缺日期/数值/单位强制转人工审核', 'P0', 'status')
    for kw, warn in [({'date': None}, '缺少完整日期'),
                     ({'value': None}, '缺少数值'),
                     ({'unit': None}, '缺少单位')]:
        res = agent.post_process({'records': [base_record(indicator_id='MACRO_CPI', **kw)],
                                  'global_warnings': []}, 'text')
        r = res['records'][0]
        c.check('status', f'{warn} → status', 'pending_review', r['status'])
        c.check('warnings', f'{warn} → 告警', True, any(warn in w for w in r['warnings']))
    cases.append(c)

    # ---------- U-10 post_process：confidence 门槛 ----------
    c = Case('U-10', '后处理-confidence<0.95 强制转人工审核', 'P1', 'status')
    low = agent.post_process({'records': [base_record(indicator_id='MACRO_CPI', confidence=0.94)],
                              'global_warnings': []}, 'text')['records'][0]
    high = agent.post_process({'records': [base_record(indicator_id='MACRO_CPI', confidence=0.96)],
                               'global_warnings': []}, 'text')['records'][0]
    c.check('status', 'confidence=0.94 → pending_review', 'pending_review', low['status'])
    c.check('status', 'confidence=0.96 且字段齐全 → ready', 'ready', high['status'],
            hard=False, note='缺陷 F-05：阈值 0.95 过严，ready 状态实际很难达成')
    cases.append(c)

    # ---------- U-11 数值 0 不被误判为缺失 ----------
    c = Case('U-11', '后处理-数值 0 不等于缺失', 'P1', 'value')
    r = agent.post_process({'records': [base_record(indicator_id='MACRO_CPI', value=0.0)],
                            'global_warnings': []}, 'text')['records'][0]
    c.check('value', 'value 保持 0', 0.0, r['value'])
    c.check('warnings', '不得出现“缺少数值”告警', False,
            any('缺少数值' in w for w in r['warnings']))
    cases.append(c)

    # ---------- U-12 输出 Schema 契约 ----------
    c = Case('U-12', 'Schema-strict 契约（全字段 required + 禁止额外属性）', 'P0', 'api_contract')
    sch = agent.schema()
    c.check('api_contract', '顶层 additionalProperties', False, sch['additionalProperties'])
    c.check('api_contract', '顶层 required', sorted(['records', 'global_warnings']),
            sorted(sch['required']))
    rec = sch['properties']['records']['items']
    c.check('api_contract', 'record additionalProperties', False, rec['additionalProperties'])
    props = set(rec['properties'])
    c.check('api_contract', '所有字段均在 required', [], sorted(props - set(rec['required'])))
    c.check('api_contract', 'status 枚举', ['ready', 'pending_review'],
            rec['properties']['status']['enum'])
    c.check('api_contract', 'change 允许 null', True,
            'null' in rec['properties']['change']['type'])
    cases.append(c)

    # ---------- U-13 pydantic 模型可用性 ----------
    c = Case('U-13', 'Schema-pydantic 模型可校验且能拦截越界值', 'P1', 'api_contract')
    ok = False
    try:
        FinancialRecord(raw_indicator='x', confidence=0.99)
        ok = True
    except Exception:
        ok = False
    c.check('api_contract', '合法记录可构造', True, ok)
    bad = False
    try:
        FinancialRecord(raw_indicator='x', confidence=1.5)
    except Exception:
        bad = True
    c.check('api_contract', 'confidence=1.5 应被拦截', True, bad)
    c.check('api_contract', 'ExtractionResult 可实例化', True,
            isinstance(ExtractionResult(input_type='text'), ExtractionResult))
    cases.append(c)

    # ---------- U-14 死代码检查：schema 模型是否被业务引用 ----------
    c = Case('U-14', '实现-Schema 模型被业务代码引用（防死代码）', 'P1', 'api_contract')
    hits = []
    for p in (ROOT / 'app').rglob('*.py'):
        if p.name == 'schemas.py':
            continue
        src = p.read_text(encoding='utf-8')
        if re.search(r'\bschemas\b|ExtractionResult|FinancialRecord', src):
            hits.append(str(p.relative_to(ROOT)))
    c.check('api_contract', 'app/ 下引用 schemas 的文件', [], hits, hard=False,
            note='缺陷 F-03：schemas.py 是死代码，响应无 pydantic 输出校验')
    cases.append(c)

    # ---------- U-15 依赖层：DeepSeek 配置生效 ----------
    c = Case('U-15', '依赖层-LLM 已切换到 DeepSeek 且 .env 被加载', 'P0', 'api_contract')
    from app.services.llm import LLMService
    svc = LLMService()
    c.check('api_contract', 'base_url', 'https://api.deepseek.com', svc.base_url)
    c.check('api_contract', '模型名非已下线的 deepseek-chat', True,
            svc.model not in ('deepseek-chat', 'deepseek-reasoner'),
            note=f'实际 model={svc.model}')
    c.check('api_contract', 'client 已构造（Key 读取成功）', True, svc.enabled())
    cases.append(c)

    # ---------- U-16 告警不重复 / 状态一致性 ----------
    c = Case('U-16', '后处理-warnings 不重复累积', 'P2', 'warnings')
    r = agent.post_process({'records': [base_record(indicator_id='MACRO_CPI', date=None,
                                                   value=None, unit=None)],
                            'global_warnings': []}, 'text')['records'][0]
    c.check('warnings', '告警去重', len(r['warnings']), len(set(r['warnings'])), hard=False,
            note='缺陷：warnings 直接 append，重复调用会累积')
    c.check('warnings', '三类缺失告警齐全', True,
            all(any(k in w for w in r['warnings']) for k in ('缺少完整日期', '缺少数值', '缺少单位')))
    cases.append(c)

    # ---------- 汇总输出 ----------
    results = []
    for c in cases:
        hard = [a for a in c.asserts if a['hard']]
        soft = [a for a in c.asserts if not a['hard']]
        hp = sum(1 for a in hard if a['ok'])
        results.append({
            'id': c.id, 'category': 'unit', 'severity': c.severity, 'title': c.title,
            'status': 'PASS' if hp == len(hard) else 'FAIL',
            'http_status': None, 'latency_ms': 0.0, 'n_records': None,
            'hard_total': len(hard), 'hard_pass': hp,
            'soft_total': len(soft), 'soft_pass': sum(1 for a in soft if a['ok']),
            'assertions': c.asserts, 'input': '(纯函数调用，无网络)', 'error': None,
            'response': None,
        })
    return results


def main():
    results = run()
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / 'results_unit.json'
    summary = {'label': 'unit', 'llm_enabled': False, 'model': '(none)',
               'total': len(results),
               'passed': sum(1 for r in results if r['status'] == 'PASS'),
               'failed': sum(1 for r in results if r['status'] == 'FAIL'),
               'errors': 0, 'generated_at': __import__('time').strftime('%Y-%m-%d %H:%M:%S')}
    p.write_text(json.dumps({'summary': summary, 'results': results}, ensure_ascii=False, indent=2),
                 encoding='utf-8')
    for r in results:
        print(f"  {'OK  ' if r['status']=='PASS' else 'FAIL'} {r['id']} {r['title']} "
              f"(hard {r['hard_pass']}/{r['hard_total']}, soft {r['soft_pass']}/{r['soft_total']})")
    print(f"\n单元层: {summary['passed']}/{summary['total']} 通过 → {p}")


if __name__ == '__main__':
    main()
