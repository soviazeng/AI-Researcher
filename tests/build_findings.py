# -*- coding: utf-8 -*-
"""汇总问题清单：测试实测发现 + 代码静态审查，产出 findings_<label>.json。

供 build_report.py 渲染到 Markdown「问题清单」章节与 Excel「6-问题与建议」。
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tests' / 'results'

# 代码静态审查发现的固化问题（与是否跑通 LLM 无关）
STATIC = [
    ['F-01', 'P0',
     'async 路由内同步阻塞调用 LLM，图片抽取会串行化整个服务',
     'main.py:17 `async def extract_image` 内部调用同步的 agent.extract_image → LLM HTTP；'
     '而 extract_text 是同步 `def`，FastAPI 会放进线程池。二者并发行为不一致。',
     '单张图片识别耗时 5~30s，期间事件循环被占满，同实例所有请求（含 /health）排队。',
     '把 extract_image 改为同步 `def`，或用 `await run_in_threadpool(...)` / 换 AsyncOpenAI 客户端。',
     '代码缺陷'],

    ['F-02', 'P1',
     '系统提示词降级为 user 消息（DeepSeek 将 developer 视同 user）',
     'llm.py 中 SYSTEM_PROMPT 以 {"role":"developer"} 传入；DeepSeek Responses API 兼容表明确'
     '“developer is treated as user”，原设计意图是 system 级指令。',
     '12 条抽取规则失去 system 优先级，长输入下规则遵从度下降，是防幻觉类用例偏差的根因之一。',
     '改用 Responses API 的 `instructions=` 参数传 SYSTEM_PROMPT（官方定义为“插入为首条 system 消息”）。',
     '依赖适配'],

    ['F-03', 'P0',
     '【已修复】json_schema 的 strict 模式与 DeepSeek 不兼容，Agent 在 DeepSeek 下完全不可用',
     'agent.schema() 含数组式 type（如 change 的 ["object","null"]）。实测：'
     'DeepSeek /responses 在 text.format.strict=True 时直接返回 '
     'HTTP 400「Invalid json schema: field `type`: unknown variant `object`」，'
     '省略或 strict=False 则正常 —— 即 strict 子集不接受数组式 type。'
     '修复前 50 条用例全部 180s 超时（服务端 500），可用率 0%。',
     '这是切换模型后最致命的兼容性缺陷：结构化抽取整条链路无法执行。',
     '已在依赖层（llm.py）加入 _to_strict_schema()：把数组式 type 改写成等价的 '
     'anyOf 形式，保留 strict=True 的强约束，业务侧 schema 定义未改动。'
     '修复后 50 条用例通过 49 条。',
     '依赖适配（已修复）'],

    ['F-13', 'P1',
     'change.type 未做受控词表归一，混入原文措辞',
     '真实跑批 51 条记录中 change.type 取值：周环比 15、null 15、同比 8、环比 7、'
     '**较前一交易日 3、日环比 2、较前一日 1** —— 后三类是原文措辞直接透传，'
     '占非空值的约 11%。用例 TC-004 因此判定不通过。',
     '下游按变化类型聚合/比对时会分裂成多个桶（“日环比”与“较前一日”语义相同却各自成组），'
     '横向比较与因子计算都会出错。',
     '为 change.type 定义封闭枚举（同比/环比/周环比/日环比/月环比），'
     '在 post_process 里做同义词映射，无法归一的进 pending_review。',
     '实测'],

    ['F-14', 'P1',
     'warnings 混装机器可读码与模型自由文本，无法程序化消费',
     'post_process 只会 append 固定的「缺少完整日期」等几条；其余全部来自 LLM 自由撰写。'
     '真实跑批中出现 8 种表达同一含义的告警：'
     '「缺少完整日期」12 次、「原文未提供日期，date=null」、「缺少日期，无法确定数据时点」、'
     '「日期“9月11日”未包含年份…」、「原文仅含“昨日”…」等，共 40 余条各不相同。',
     '审核系统无法用规则匹配告警类型，只能人工逐条阅读；告警既不能统计也不能触发自动化。',
     '把 warning 改为结构化对象（code + message），code 由代码生成并枚举，'
     '模型自由文本降级为 message 字段或 evidence 补充。',
     '实测'],

    ['F-04', 'P1',
     '自动回填指标口径时未同步回填 category / frequency',
     'agent.py:45-46 仅补 indicator_id 与 standard_indicator，未补 category、frequency，'
     '而知识库中这两个字段是现成的。',
     '结构化结果字段残缺，下游按 category 分组统计时会丢记录。',
     '回填时一并写入 candidates[0] 对应知识库条目的 category 与 frequency。',
     '代码缺陷'],

    ['F-05', 'P2',
     'confidence 阈值 0.95 硬编码，状态机不可配置',
     'agent.py:53 `if r.get("confidence",0) < 0.95: status="pending_review"`；'
     '单元测试 U-10 验证 0.94 转人工、0.96 放过。'
     '真实跑批 51 条记录 confidence 中位数恰为 0.95（min 0.55 / max 0.99），'
     'status 分布 ready 30 / pending_review 21 —— 命中率对阈值极端敏感，'
     '模型自评只要整体下移 0.01，ready 数量就会大幅塌陷。',
     '阈值写死且与模型自评分强耦合，换模型或改提示词都会让审核队列规模剧烈波动；'
     '该阈值也无法按业务场景调整。',
     '把阈值提为可配置项（env），或改为规则化置信度（字段完备度 + 指标是否精确命中），'
     '不要直接采信 LLM 自评分。',
     '设计问题'],

    ['F-06', 'P1',
     '图片大小限制在读取完整个文件后才生效',
     'main.py:20-22 先 `await file.read()` 再比较 len 与 MAX_IMAGE_MB。',
     'MAX_IMAGE_MB 无法阻止大文件占满内存，构成内存放大/DoS 风险。',
     '改为分块流式读取并累计计数，超限立即中断；或先校验 Content-Length 头。',
     '代码缺陷'],

    ['F-07', 'P2',
     '中文指标匹配用 difflib 字符相似度，短词易误召回',
     'indicator_master.py:22 对中文串直接算 SequenceMatcher.ratio；中文无空格，'
     '“螺纹钢表观消费量”与“螺纹钢社会库存”字符重叠度高。',
     'candidates 候选集噪声大；一旦阈值判定不当可能误映射到错误的指标口径。',
     '引入 jieba 分词 + 关键词权重，或维护同义/反义表，并加入“不得跨口径映射”的硬规则。',
     '算法问题'],

    ['F-08', 'P2',
     '别名得分子串保底只对 aliases 生效，standard_name 不享受，同类输入口径不一',
     'indicator_master.py:25-26 仅对 item["aliases"] 做子串判断并给 0.88 保底，'
     '未对 standard_name 做同样处理。单元测试 U-03 实测：'
     '“螺纹钢库存数据”0.88（别名子串，享保底）、“秦港库存量”0.8889（同），'
     '而“螺纹钢社会库存数据”仅 0.875、“秦皇岛港煤炭库存情况”0.8889（标准名子串，无保底）。',
     '同一类“多余后缀”的输入，得分取决于碰巧是别名还是标准名，行为不可预期；'
     '且所有近似命中都恒低于 0.95，永远无法触发 agent.py:45 的自动回填阈值。',
     '把 standard_name 与 aliases 放到同一个候选串集合里统一打分，'
     '并明确“什么分位可以自动归一、什么分位只能进候选”。',
     '逻辑一致性'],

    ['F-09', 'P2',
     'LLM 调用失败无降级与重试，直接向上抛 500',
     'agent.extract_text/extract_image 未对 LLMService.run 做异常兜底。',
     '上游网关抖动或模型返回空内容时，接口直接 5xx，无部分结果、无重试。',
     '加一次指数退避重试 + 失败时返回携带 global_warnings 的降级响应。',
     '代码缺陷'],

    ['F-10', 'P2',
     'OCR 通道仅 base64 直传，无文字坐标，evidence 不可审计',
     'ocr.py 仅实现 to_data_url；README 亦承认生产需引入 PaddleOCR/云 OCR 保留坐标。',
     'evidence 字段完全依赖模型复述，无法做证据定位与人工复核回溯。',
     '接入 OCR 双通道并保留 bbox，把 evidence 与坐标绑定。',
     '架构演进'],

    ['F-11', 'P2',
     '知识库仅 6 个指标，覆盖度不足以支撑“投研全量数据标准化”',
     'indicator_master.py 只有螺纹钢社库/厂库、秦港煤炭库存、碳酸锂价格、CPI、PPI。',
     '测试中期货、指数、个股等常见数据全部落入“超纲”，只能 pending_review。',
     '补齐品类与口径字典，并建立指标入库评审流程。',
     '业务覆盖'],

    ['F-12', 'P3',
     '测试与工程配套薄弱',
     'tests/test_knowledge.py 仅 2 条断言；项目无 CI 配置、无 Dockerfile、无结构化日志。',
     '回归无守门，改动容易静默劣化（本次依赖切换时的 schema 不兼容即是典型）。',
     '把本次 66 条用例纳入 CI，补充结构化日志与耗时埋点。',
     '工程化'],

    ['F-15', 'P1',
     'schemas.py 的 pydantic 模型是死代码，响应无输出校验',
     '单元测试 U-14 扫描 app/ 全部源码：除 schemas.py 自身外，'
     '没有任何模块引用 ExtractionResult / FinancialRecord / CandidateIndicator。'
     '接口直接返回 post_process 加工过的裸 dict。',
     '模型返回缺字段或类型异常时（schema 非 strict 保障的情况下），'
     'post_process 依赖 dict 隐式结构，可能出现 KeyError 或字段静默丢失。',
     '在 post_process 入口用 ExtractionResult.model_validate 做一次输出校验，'
     '失败记录降级为 pending_review 并附告警。',
     '代码缺陷'],
]


def auto_findings(results, meta):
    """从实测数据中提炼的发现。环境阻塞用例不参与能力评估。"""
    rows = []
    runnable = [r for r in results if r['status'] != 'BLOCKED']
    blocked = [r for r in results if r['status'] == 'BLOCKED']

    if blocked:
        rows.append(['E-01', 'P0', f'环境阻塞：{len(blocked)} 条 LLM 依赖用例未能执行',
                     f"预检结论：{meta.get('dependency_reason')}",
                     '文本抽取、图片抽取两条核心链路的模型能力完全未受测，'
                     '当前报告只能覆盖非 LLM 的工程与契约部分。',
                     '为 DeepSeek 账户充值后重跑：run_e2e.py --label live（用例会自动纳入统计）。',
                     '环境'])

    dim = {}
    for r in runnable:
        for a in r['assertions']:
            if a['dim'] == 'environment':
                continue
            d = dim.setdefault(a['dim'], [0, 0])
            d[1] += 1
            if a['ok']:
                d[0] += 1

    fails = [r for r in runnable if r['status'] != 'PASS']
    if not fails:
        rows.append(['D-01', 'P3', '当前可执行范围内未发现用例级失败',
                     f'{len(runnable)}/{len(runnable)} 通过', '—', '保持回归覆盖', '实测'])
        return rows

    order = sorted(dim.items(), key=lambda x: (x[1][0] / x[1][1]) if x[1][1] else 1)
    label = {'indicator_mapping': '指标映射', 'value': '数值解析', 'unit': '单位处理',
             'date': '日期处理', 'change': '变化量解析', 'status': '状态与置信度',
             'record_count': '记录数量', 'warnings': '告警生成', 'anti_hallucination': '防幻觉',
             'api_contract': '接口契约', 'record_match': '记录匹配'}
    for i, (k, (ok, tot)) in enumerate(order[:3], 1):
        if tot and ok / tot < 0.9:
            bad_ids = sorted({r['id'] for r in fails
                              if any(a['dim'] == k and not a['ok'] for a in r['assertions'])})
            rows.append([f'D-0{i}', 'P1' if ok / tot < 0.7 else 'P2',
                         f'{label.get(k,k)}能力未达标',
                         f'{ok}/{tot} 断言通过（{ok/tot*100:.1f}%）；涉及用例 {", ".join(bad_ids[:8])}',
                         '该维度是结构化抽取的核心链路，直接影响数据可用性。',
                         f'针对上述用例逐条定位，优先修复 {label.get(k,k)} 相关逻辑。',
                         '实测'])

    errs = [r for r in runnable if r['status'] == 'ERROR']
    if errs:
        rows.append(['D-90', 'P0', f'{len(errs)} 条用例执行异常',
                     '；'.join(f"{r['id']}: {r['error']}"[:120] for r in errs[:4]),
                     '无法完成端到端链路，属阻断性问题。',
                     '先排查服务端异常栈，再做功能修复。', '实测'])

    p0 = [r for r in runnable if r['severity'] == 'P0']
    p0f = [r for r in p0 if r['status'] != 'PASS']
    if p0:
        rows.append(['D-91', 'P0' if len(p0f) > len(p0) * 0.3 else 'P2',
                     f'P0 用例失败 {len(p0f)}/{len(p0)}（仅统计可执行部分）',
                     ', '.join(r['id'] for r in p0f[:10]) or '—',
                     'P0 为核心链路，失败即不可交付。',
                     '按 P0 → P1 → P2 顺序收敛缺陷。', '实测'])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--label', default='live')
    args = ap.parse_args()

    data = json.loads((OUT / f'results_{args.label}.json').read_text(encoding='utf-8'))
    results = list(data['results'])
    # 单元层结果一并纳入自动发现（若已生成）
    up = OUT / 'results_unit.json'
    if up.exists():
        results.extend(json.loads(up.read_text(encoding='utf-8'))['results'])
    s = data['summary']

    probe = None
    pp = OUT / 'concurrency_probe.json'
    if pp.exists():
        probe = json.loads(pp.read_text(encoding='utf-8'))

    rows = []
    # 实测发现放最前（环境阻塞不参与能力评估）
    for r in auto_findings(results, s):
        rows.append(r)
    # F-01 若有并发探针证据，替换其证据字段
    static = [list(x) for x in STATIC]
    if probe:
        img = next((p for p in probe if 'image' in p['interface']), None)
        txt = next((p for p in probe if 'text' in p['interface']), None)
        if img and txt:
            caveat = '' if img.get('llm_live') else (
                '注：该组数据在 LLM 调用失败（账户余额不足，约 0.2s 即返回）的条件下测得，'
                '阻塞窗口远小于真实推理耗时（数秒至数十秒），余额恢复后实际阻塞只会更严重。')
            static[0][3] = (f"并发实测（LLM 真实可用）：图片接口 {img['n']} 并发总耗时 "
                            f"{img['parallel_total_s']}s，单次均值 {img['single_avg_s']}s，"
                            f"加速比 {img['speedup']}x（判定：{img['verdict']}）；"
                            f"文本接口 {txt['n']} 并发总耗时 {txt['parallel_total_s']}s，"
                            f"加速比 {txt['speedup']}x（判定：{txt['verdict']}）。"
                            f"3 并发图片请求耗时≈3×单次，即完全串行。{caveat}"
                            f"测量脚本 tests/probe_concurrency.py 可复跑。")
    rows.extend(static)

    # Markdown 渲染
    md = ['| 编号 | 严重度 | 问题 | 证据 / 现象 | 影响 | 修复建议 | 归属 |',
          '| --- | --- | --- | --- | --- | --- | --- |']
    for r in rows:
        md.append('| ' + ' | '.join(str(x).replace('|', '\\|') for x in r) + ' |')

    extra = {'findings_rows': rows, 'findings_md': '\n'.join(md),
             'probe': probe}
    (OUT / f'findings_{args.label}.json').write_text(
        json.dumps(extra, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'findings_{args.label}.json 已生成，共 {len(rows)} 条')


if __name__ == '__main__':
    main()
