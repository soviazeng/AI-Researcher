# 投研非结构化数据智能采集与标准化 Agent V1.1

V1.1 = Vision 图片输入 + LLM金融语义理解 + Indicator Knowledge Base + Structured Outputs。

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
