import base64

class VisionOCR:
    # V1.1 用Vision直接读图；后续可替换PaddleOCR/云OCR并保留坐标。
    def to_data_url(self, content: bytes, content_type: str) -> str:
        return f'data:{content_type};base64,{base64.b64encode(content).decode()}'
