import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------------
# 依赖层适配：把 LLM 后端从 OpenAI 切到 DeepSeek。
#
# 说明（业务逻辑保持不变，仅替换底层依赖）：
#  1. DeepSeek 官方提供 Responses API（POST https://api.deepseek.com/responses），
#     请求体与 OpenAI Responses API 同构，因此 client.responses.create(...) 的
#     调用方式可原样保留，只换 base_url / api_key / model。
#  2. 模型名：deepseek-chat / deepseek-reasoner 已于 2026-07-24 下线；
#     当前可用 deepseek-flash（文本+图片）与 deepseek-v4-pro（纯文本）。
#  3. 原代码 requirements 里声明了 python-dotenv 但从未调用 load_dotenv()，
#     导致 README 承诺的 .env 实际不生效，这里补上。
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / '.env')

DEFAULT_BASE_URL = 'https://api.deepseek.com'
DEFAULT_MODEL = 'deepseek-flash'


def _to_strict_schema(node):
    """把 JSON Schema 里的数组式 type（如 ['object','null']）改写成 anyOf 形式。

    DeepSeek 的 json_schema strict 模式只接受受限子集：`type` 不允许是数组，
    否则报错 `Invalid json schema: field 'type': unknown variant 'object'`（HTTP 400）。
    改写成 `anyOf: [<原约束, type=X>, {"type":"null"}]` 后可正常通过，
    语义等价，且 OpenAI 侧同样接受 anyOf，因此两边兼容。

    该转换只发生在依赖边界，业务侧 schema 定义（agent.schema）保持原样。
    """
    if isinstance(node, dict):
        t = node.get('type')
        if isinstance(t, list):
            rest = [x for x in t if x != 'null']
            base = {k: v for k, v in node.items() if k != 'type'}
            variants = [dict(base, type=x) for x in rest]
            if 'null' in t:
                variants.append({'type': 'null'})
            if len(variants) == 1:
                return _to_strict_schema(variants[0])
            return {'anyOf': [_to_strict_schema(v) for v in variants]}
        return {k: _to_strict_schema(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_to_strict_schema(x) for x in node]
    return node


class LLMService:
    def __init__(self):
        self.model = os.getenv('OPENAI_MODEL') or os.getenv('DEEPSEEK_MODEL') or DEFAULT_MODEL
        key = os.getenv('DEEPSEEK_API_KEY') or os.getenv('OPENAI_API_KEY')
        base_url = os.getenv('OPENAI_BASE_URL') or os.getenv('DEEPSEEK_BASE_URL') or DEFAULT_BASE_URL
        self.base_url = base_url
        self.client = OpenAI(api_key=key, base_url=base_url) if key else None
        self.last_error = None

    def enabled(self):
        return self.client is not None

    def run(self, developer_prompt, user_content, schema):
        if not self.client:
            raise RuntimeError('未设置 DEEPSEEK_API_KEY')
        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {'role': 'developer', 'content': [{'type': 'input_text', 'text': developer_prompt}]},
                    {'role': 'user', 'content': user_content}
                ],
                text={'format': {
                    'type': 'json_schema',
                    'name': 'financial_data_extraction',
                    'strict': True,
                    'schema': _to_strict_schema(schema)
                }}
            )
        except Exception as exc:                     # 依赖层：把 SDK/网络异常收敛成可读错误
            self.last_error = f'{exc.__class__.__name__}: {exc}'
            raise
        text = getattr(response, 'output_text', None)
        if not text:
            self.last_error = f'空响应 output_text={text!r}'
            raise RuntimeError(self.last_error)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            self.last_error = f'JSONDecodeError: {exc}; raw={text[:200]!r}'
            raise
