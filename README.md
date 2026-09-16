# 投研非结构化数据智能采集与标准化 Agent V1.1

过往的投研活动中，业务流程是业务员看到数据 → 微信聊天 → 截图 → 人脑记忆 → Excel → 投研人员再加工。

变成：

业务员截图-AI识别-标准指标-自动入库-数据质量检查-投研数据库-行情数据/内部数据融合-投研分析-AI问答。
形成Vision 图片输入 + LLM金融语义理解 + Indicator Knowledge Base + Structured Outputs。

1. Vision 图片理解

可以直接：

POST /api/v1/extract/image

上传：

微信截图
企业微信截图
Wind 截图
网页截图
研报截图
手机拍照
表格截图

模型直接读取图片中的金融数据。

2. LLM Financial Agent

不再只是 OCR，而是让 Agent 判断：
“RB库存512.3万吨”
        ↓
RB库存
        ↓
螺纹钢社会库存
        ↓
512.3
        ↓
万吨
        ↓
对应观察日期
        ↓
标准金融数据

3. Indicator Knowledge Base

目前已经内置第一批指标：

螺纹钢社会库存
螺纹钢厂库
秦皇岛港煤炭库存
碳酸锂价格
CPI
PPI
...
并支持：

标准名称
+
别名
+
模糊匹配
+
候选指标
+
匹配分数

4. Structured Output

Agent 不允许自由发挥 JSON，而是按照严格 Schema 输出：
indicator
date
value
unit
frequency
change
market
region
source
evidence
confidence
status
candidates


## 启动
```bash
python -m venv .venv
pip install -r requirements.txt
copy .env.example .env
```

.env：
```env
OPENAI_API_KEY=你的Key
OPENAI_MODEL=gpt-5.6-luna
```

```bash
uvicorn app.main:app --reload
```

Swagger: http://127.0.0.1:8000/docs

## API
- POST /api/v1/extract/text
- POST /api/v1/extract/image
- GET /health

## 架构
图片 → Vision → 金融语义Agent → Indicator Knowledge Base → Structured Output → 规则校验 → JSON

生产环境建议加入PaddleOCR/云OCR双通道并保留文字坐标，用于证据定位、审计和人工审核。
