from typing import Any, Optional, Dict

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse


class FormatJSONResponse(JSONResponse):
    def __init__(self,
                 data: Any = None,
                 code: int = 200,
                 message: str = 'success',
                 status_code: int = 200,
                 headers: Optional[Dict[str, str]] = None,
                 background: Optional[BackgroundTask] = None
                 ) -> None:
        processed_data = self._add_statistics(data)
        content = jsonable_encoder({
            'code': code,
            'message': message,
            'data': processed_data
        })
        super().__init__(content=content, status_code=status_code,
                         headers=headers, media_type='application/json; charset=utf-8', background=background)

    def _add_statistics(self, data: Any) -> Any:
        if isinstance(data, list):
            return {
                'items': data,
                'total': len(data),
                'count': len(data)
            }
        elif isinstance(data, dict):
            if 'items' in data and 'total' in data:
                return data
            elif isinstance(data.get('data'), list):
                data['data'] = {
                    'items': data['data'],
                    'total': len(data['data']),
                    'count': len(data['data'])
                }
                return data
            else:
                return data
        else:
            return data

class Token(BaseModel):
    access_token: str
    token_type: str

class ChatRequest(BaseModel):

    question: str
    collection_name: Optional[str] = None

class ChartRequest(BaseModel):
    data_source: dict
    requirements: dict

class ReportRequest(BaseModel):

    question: str
    structure_data: dict
