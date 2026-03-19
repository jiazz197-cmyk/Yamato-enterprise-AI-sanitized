"""
智能组合秤订单填表 API
"""
from datetime import datetime
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.logging import get_logger
from app.integrations.doc_processing.embedding_store import (
    BGEM3EmbeddingWrapper,
    VectorStoreManager,
)
from app.integrations.doc_processing.exceptions import EmbeddingError, VectorStoreError
from app.integrations.doc_processing.pipeline import clean_text_for_postgres
from app.schemas.endpoints.closing_form import (
    ClosingFormListResponse,
    ClosingFormRecord,
    ClosingFormSubmit,
    ClosingFormSubmitResponse,
)
from llama_index.core.schema import TextNode

router = APIRouter()
logger = get_logger("closing_form")

# 填表写入的目标表：data_doc_collection_1（PGVectorStore 会自动加 data_ 前缀，故传 doc_collection）
CLOSING_FORM_TABLE_PREFIX = "doc_collection"
CLOSING_FORM_INSTANCE_ID = 1


@router.post("/submit", response_model=ClosingFormSubmitResponse)
async def submit_closing_form(
    form_data: ClosingFormSubmit,
    x_username: str = Header(default="anonymous", alias="X-Username", description="由前端从登录态中获取并注入的用户名"),
):
    """
    提交智能组合秤订单填表数据

    将表单数据格式化为文本，调用 BGE-M3 进行 1024 维向量化，
    写入 data_doc_collection_1 表的 text、metadata_、embedding 列。

    前端须在请求头中携带 `X-Username`，值为当前登录用户名。
    支持 URL 编码（如 %E5%BC%A0%E4%B8%89），后端会自动解码。
    """
    try:
        # 0. URL 解码用户名（支持前端传中文等非 ASCII 字符的编码形式）
        uploader = unquote(x_username, encoding="utf-8")

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
        db_config = {
            "host": settings.POSTGRES_SERVER,
            "user": settings.POSTGRES_USER,
            "password": settings.POSTGRES_PASSWORD,
            "database": settings.POSTGRES_DB,
            "port": settings.POSTGRES_PORT,
        }
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


# 填表记录所在的 PostgreSQL 表（LlamaIndex PGVectorStore 自动加 data_ 前缀）
_CLOSING_FORM_TABLE = f"data_{CLOSING_FORM_TABLE_PREFIX}_{CLOSING_FORM_INSTANCE_ID}"


@router.get("/list", response_model=ClosingFormListResponse)
async def list_closing_forms(
    x_username: str = Header(default="anonymous", alias="X-Username", description="当前登录用户名"),
    db: Session = Depends(get_db),
):
    """
    查询当前用户已提交的填表记录

    从 data_doc_collection_1 表中按 metadata_->>'uploader' 过滤，
    按 id 倒序返回该用户的所有历史表单。
    """
    try:
        uploader = unquote(x_username, encoding="utf-8")

        rows = db.execute(
            text(
                f"SELECT id, text, metadata_->>'upload_time' AS upload_time"
                f" FROM {_CLOSING_FORM_TABLE}"
                f" WHERE metadata_->>'uploader' = :uploader"
                f" ORDER BY metadata_->>'upload_time' DESC"
            ),
            {"uploader": uploader},
        ).fetchall()

        records = [
            ClosingFormRecord(
                id=str(row.id),
                text=row.text or "",
                upload_time=row.upload_time,
            )
            for row in rows
        ]

        logger.info("查询填表记录: uploader=%s, count=%d", uploader, len(records))
        return ClosingFormListResponse(success=True, total=len(records), records=records)

    except Exception as e:
        logger.exception("查询填表记录失败")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
