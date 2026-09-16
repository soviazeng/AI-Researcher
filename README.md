# 投研非结构化数据智能采集与标准化 Agent V1.1

过往的投研活动中，业务流程是业务员看到数据 → 微信聊天 → 截图 → 人脑记忆 → Excel → 投研人员再加工
变成：
业务员截图-AI识别-标准指标-自动入库-数据质量检查-投研数据库-行情数据/内部数据融合-投研分析-AI问答

形成Vision 图片输入 + LLM金融语义理解 + Indicator Knowledge Base + Structured Outputs。

                非结构化信息
                      │
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
      截图          聊天记录        PDF
        ↓             ↓             ↓
        └─────────────┼─────────────┘
                      ↓
                 AI数据抽取
                      ↓
                金融指标标准层
                      ↓
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
      行情数据       另类数据       人工数据
        │             │             │
        └─────────────┼─────────────┘
                      ↓
                 金融数据中台
                      ↓
                ┌─────┴─────┐
                ↓           ↓
             BI分析       AI助手
                ↓           ↓
             图表/报告    自然语言问答
             
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
