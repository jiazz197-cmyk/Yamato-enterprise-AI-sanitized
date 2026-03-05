"""
智能组合秤订单填表 API
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.doc_processing.embedding_store import (
    BGEM3EmbeddingWrapper,
    VectorStoreManager,
)
from app.integrations.doc_processing.exceptions import EmbeddingError, VectorStoreError
from app.integrations.doc_processing.pipeline import clean_text_for_postgres
from app.schemas.endpoints.closing_form import (
    ClosingFormSubmit,
    ClosingFormSubmitResponse,
)
from llama_index.core.schema import TextNode

router = APIRouter()
logger = get_logger("closing_form")

# 填表写入的目标表：data_doc_collection_1（PGVectorStore 会自动加 data_ 前缀，故传 doc_collection）
CLOSING_FORM_TABLE_PREFIX = "doc_collection"
CLOSING_FORM_INSTANCE_ID = 1


def _get_db_config() -> dict:
    """获取数据库配置"""
    return {
        "host": settings.POSTGRES_SERVER,
        "user": settings.POSTGRES_USER,
        "password": settings.POSTGRES_PASSWORD,
        "database": settings.POSTGRES_DB,
        "port": settings.POSTGRES_PORT,
    }


@router.post("/submit", response_model=ClosingFormSubmitResponse)
async def submit_closing_form(
    form_data: ClosingFormSubmit,
    uploader: str = Query(default="anonymous", description="上传用户名"),
):
    """
    提交智能组合秤订单填表数据

    将表单数据格式化为文本，调用 BGE-M3 进行 1024 维向量化，
    写入 data_doc_collection_1 表的 text、metadata_、embedding 列。
    """
    try:
        # 1. 生成格式化的表单文本
        form_text = form_data.to_formatted_text()
        form_text = clean_text_for_postgres(form_text)

        # 2. 构建 metadata（用户名、上传时间）
        upload_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        metadata = {
            "uploader": uploader,
            "upload_time": upload_time,
        }

        # 3. 创建 TextNode
        node = TextNode(text=form_text, metadata=metadata)

        # 4. 初始化嵌入模型和向量存储
        db_config = _get_db_config()
        embedding_model = BGEM3EmbeddingWrapper()
        vector_store_manager = VectorStoreManager(
            db_config=db_config,
            table_prefix=CLOSING_FORM_TABLE_PREFIX,
        )

        # 5. 向量化并写入 PGVector
        vector_store_manager.upsert_chunks(
            chunks=[node],
            instance_id=CLOSING_FORM_INSTANCE_ID,
            embedding_model=embedding_model,
        )

        logger.info(
            "填表提交成功: uploader=%s, upload_time=%s",
            uploader,
            upload_time,
        )

        return ClosingFormSubmitResponse(
            success=True,
            message="提交成功",
            form_text=form_text,
        )

    except EmbeddingError as e:
        logger.error("填表嵌入失败: %s", e)
        raise HTTPException(status_code=503, detail=f"嵌入服务异常: {str(e)}")
    except VectorStoreError as e:
        logger.error("填表写入向量存储失败: %s", e)
        raise HTTPException(status_code=500, detail=f"写入失败: {str(e)}")
    except Exception as e:
        logger.exception("填表提交失败")
        raise HTTPException(status_code=500, detail=f"提交失败: {str(e)}")
