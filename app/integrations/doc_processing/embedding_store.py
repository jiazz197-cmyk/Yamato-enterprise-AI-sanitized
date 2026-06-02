import logging
import math
from pathlib import Path
from typing import Dict, List, Optional
import threading

import httpx
import torch
from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.schema import TextNode
from llama_index.vector_stores.postgres import PGVectorStore
from pydantic import Field

from app.core.config import settings
from app.core.http_client import get_http_client
from .exceptions import EmbeddingError, VectorStoreError

logger = logging.getLogger(__name__)


_EMBEDDING_INSTANCES: Dict[str, "BGEM3EmbeddingWrapper"] = {}
_EMBEDDING_LOCK = threading.Lock()


class BGEM3EmbeddingWrapper(BaseEmbedding):
    """BGE-M3 嵌入封装（通过 Docker HTTP 接口调用远程模型）"""

    model: object = Field(description="BGE-M3 远程 API 占位")
    api_url: str = Field(default="", description="BGE-M3 嵌入服务地址")
    model_name: str = Field(default="", description="BGE-M3 模型名称")

    def __init__(
        self,
        api_url: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        try:
            if api_url is None:
                api_url = settings.BGE_M3_API_URL
            if model_name is None:
                # 需与服务启动时的 --served-model-name 保持一致
                model_name = settings.BGE_M3_MODEL_NAME

            # 不再本地加载模型，model 只是占位；api_url / model_name 作为字段传入
            super().__init__(model=None, api_url=api_url, model_name=model_name)

            cache_key = f"{self.api_url}:{self.model_name}"
            with _EMBEDDING_LOCK:
                _EMBEDDING_INSTANCES[cache_key] = self

            logger.info("BGE-M3 远程接口初始化完成: %s (model=%s)", self.api_url, self.model_name)
        except Exception as exc:
            raise EmbeddingError(f"初始化 BGE-M3 远程接口失败: {exc}") from exc

    def _parse_embedding(self, data: dict) -> List[float]:
        embedding = None
        if isinstance(data, dict):
            if "data" in data and data["data"]:
                first_item = data["data"][0]
                embedding = first_item.get("embedding") or first_item.get("vector")
            else:
                embedding = data.get("embedding") or data.get("vector")

        if not isinstance(embedding, list):
            raise ValueError(f"远程接口返回格式不符合预期: {data}")

        if any(math.isnan(x) or math.isinf(x) for x in embedding):
            logger.warning("检测到 NaN/Inf 嵌入，返回零向量")
            return [0.0] * len(embedding)

        return embedding

    async def _fetch_embedding(self, text: str) -> List[float]:
        if not text or not text.strip():
            return [0.0] * 1024

        payload = {
            "model": self.model_name,
            "input": [text],
        }
        client = await get_http_client()
        response = await client.post(self.api_url, json=payload, timeout=30)
        response.raise_for_status()
        return self._parse_embedding(response.json())

    def _fetch_embedding_sync(self, text: str) -> List[float]:
        if not text or not text.strip():
            return [0.0] * 1024

        payload = {
            "model": self.model_name,
            "input": [text],
        }
        with httpx.Client(timeout=30) as client:
            response = client.post(self.api_url, json=payload)
            response.raise_for_status()
            return self._parse_embedding(response.json())

    def _get_text_embedding(self, text: str) -> List[float]:
        try:
            return self._fetch_embedding_sync(text)
        except Exception as exc:
            logger.exception("调用远程 BGE-M3 接口生成嵌入失败")
            raise EmbeddingError(f"调用远程 BGE-M3 接口失败: {exc}") from exc

    def _get_query_embedding(self, query: str) -> List[float]:
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return await self._fetch_embedding(query)

    async def _aget_text_embedding(self, text: str) -> List[float]:
        return await self._fetch_embedding(text)

    def embed_text(self, text: str) -> List[float]:
        """对外暴露的文本向量化接口"""
        return self._get_text_embedding(text)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """批量向量化文本（逐条调用远程接口）"""
        return [self._get_text_embedding(text) for text in texts]

    @classmethod
    def cleanup_all_instances(cls):
        """清理缓存的模型实例（远程模式下主要清理缓存字典）"""
        with _EMBEDDING_LOCK:
            for key in list(_EMBEDDING_INSTANCES.keys()):
                logger.info("清理 BGE-M3 远程实例: %s", key)
                _EMBEDDING_INSTANCES.pop(key, None)

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.info("GPU 缓存已清理")

    def get_memory_info(self) -> Dict:
        """查看当前使用信息（远程模式主要展示接口信息）"""
        info = {
            "mode": "remote",
            "api_url": getattr(self, "api_url", ""),
            "model_name": getattr(self, "model_name", ""),
            "instances_count": len(_EMBEDDING_INSTANCES),
        }
        if torch.cuda.is_available():
            info.update(
                {
                    "gpu_allocated_mb": torch.cuda.memory_allocated() / 1024 / 1024,
                    "gpu_reserved_mb": torch.cuda.memory_reserved() / 1024 / 1024,
                }
            )
        return info


class VectorStoreManager:
    """封装 PGVector 存储"""

    def __init__(self, db_config: Dict, table_prefix: str = "doc_collection"):
        self.db_config = db_config
        self.table_prefix = table_prefix
        # 注意：PGVector 数据存储在 PostgreSQL 中，不需要本地持久化
        # 如果需要使用本地存储（例如 FAISS），可以取消下面的注释：
        # self.persist_base_dir = Path("./index_storage")

    def _build_vector_store(self, instance_id: int) -> PGVectorStore:
        collection_name = f"{self.table_prefix}_{instance_id}"
        try:
            return PGVectorStore.from_params(
                database=self.db_config["database"],
                host=self.db_config["host"],
                password=self.db_config["password"],
                port=self.db_config["port"],
                user=self.db_config["user"],
                table_name=collection_name,
                embed_dim=1024,
            )
        except Exception as exc:
            raise VectorStoreError(f"创建 PGVectorStore 失败: {exc}") from exc

    # 注意：PGVector 不需要本地持久化目录，数据存储在 PostgreSQL 中
    # 如果使用本地存储（例如 FAISS），可以取消下面的注释：
    # def get_persist_dir(self, instance_id: int) -> Path:
    #     persist_dir = self.persist_base_dir / f"index_storage_{self.table_prefix}_{instance_id}"
    #     persist_dir.mkdir(parents=True, exist_ok=True)
    #     return persist_dir

    def upsert_chunks(self, chunks: List[TextNode], instance_id: int, embedding_model: BGEM3EmbeddingWrapper):
        """
        将文档块写入向量存储
        
        当前实现：使用 PGVector（PostgreSQL），数据直接存储在数据库中
        """
        try:
            vector_store = self._build_vector_store(instance_id)
            
            # [note] 对于 PGVector：不需要本地持久化存储，直接创建新的 StorageContext
            # 数据已经存储在 PostgreSQL 中，不需要 docstore.json
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            Settings.embed_model = embedding_model
            
            index = VectorStoreIndex.from_vector_store(
                vector_store,
                storage_context=storage_context,
                embed_model=embedding_model,
                show_progress=False,
            )
            index.insert_nodes(chunks)
            
            logger.info("成功写入 PGVector: %s 条 (instance_id=%s)", len(chunks), instance_id)
            
        except Exception as exc:
            raise VectorStoreError(f"写入 PGVector 失败: {exc}") from exc
        
        # ==================== 原本地存储实现（已废弃，仅供参考）====================
        # 如果需要使用本地持久化存储（例如 FAISS），可以参考以下代码：
        # 
        # try:
        #     vector_store = self._build_vector_store(instance_id)
        #     persist_dir = self.get_persist_dir(instance_id)
        #
        #     storage_context = StorageContext.from_defaults(
        #         vector_store=vector_store, 
        #         persist_dir=persist_dir
        #     )
        #     Settings.embed_model = embedding_model
        #     index = VectorStoreIndex.from_vector_store(
        #         vector_store,
        #         storage_context=storage_context,
        #         embed_model=embedding_model,
        #         show_progress=False,
        #     )
        #     index.insert_nodes(chunks)
        #     index.storage_context.persist(persist_dir=persist_dir)
        #     logger.info("成功写入向量存储: %s 条", len(chunks))
        # except Exception as exc:
        #     raise VectorStoreError(f"写入向量存储失败: {exc}") from exc
        # ====================================================================

