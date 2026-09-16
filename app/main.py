import os
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from app.services.agent import FinancialDataAgent

app = FastAPI(title='投研非结构化数据智能采集与标准化 Agent', version='1.1.0')
agent = FinancialDataAgent()

@app.get('/health')
def health():
    return {'status': 'ok', 'version': '1.1.0'}

@app.post('/api/v1/extract/text')
def extract_text(text: str = Form(...), context: str = Form('')):
    return agent.extract_text(text, context)

@app.post('/api/v1/extract/image')
async def extract_image(file: UploadFile = File(...), context: str = Form('')):
    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(400, '仅支持图片文件')
    content = await file.read()
    if len(content) > int(os.getenv('MAX_IMAGE_MB', '20')) * 1024 * 1024:
        raise HTTPException(400, '图片超过大小限制')
    return agent.extract_image(content, file.content_type, context)
