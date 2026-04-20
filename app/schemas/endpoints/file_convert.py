from typing import Optional, List

from pydantic import BaseModel


class ExcelConvertRequest(BaseModel):
    """Excel 转换请求模型"""
    filepath: str
    sheet_idx: Optional[int] = 0
    skiprows: Optional[List[int]] = None
    header_rows: Optional[int] = 2


class ExcelConvertResponse(BaseModel):
    """Excel 转换响应模型"""
    sheet_name: str
    headers: List[str]
    rows: List[dict]


class PdfConvertRequest(BaseModel):
    """PDF 转换请求模型"""
    filepath: str


class PdfConvertResponse(BaseModel):
    """PDF 转换响应模型"""
    text: str 