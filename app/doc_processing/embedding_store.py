import logging
import math
import os
from pathlib import Path
from typing import Dict, List, Optional
import threading

import torch
from FlagEmbedding import BGEM3FlagModel
from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.schema import TextNode
from llama_index.vector_stores.postgres import PGVectorStore
from pydantic import Field

from .exceptions import EmbeddingError, VectorStoreError

logger = logging.getLogger(__name__)


_EMBEDDING_INSTANCES: Dict[str, "BGEM3EmbeddingWrapper"] = {}
_EMBEDDING_LOCK = threading.Lock()


class BGEM3EmbeddingWrapper(BaseEmbedding):
    """BGE-M3 嵌入封装"""
    model: object = Field(description="BGE-M3 模型实例")

    def __init__(self, model_path: Optional[str] = None, device: str = "auto"):
        try:
            if model_path is None:
                model_path = os.environ.get("AI_MODEL_PATH", "ai_models/bge-m3")
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            model = BGEM3FlagModel(
                model_path,
                use_fp16=False,
                device=device,
                pooling_method="cls",
            )
            super().__init__(model=model)
            self._model_path = model_path
            self._device = device
            cache_key = f"{model_path}:{device}"
            with _EMBEDDING_LOCK:
                _EMBEDDING_INSTANCES[cache_key] = self
        except Exception as exc:
            raise EmbeddingError(f"初始化 BGE-M3 失败: {exc}") from exc

    def _get_text_embedding(self, text: str) -> List[float]:
        if not text or not text.strip():
            return [0.0] * 1024

        try:
            result = self.model.encode(
                [text],
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
                batch_size=1,
            )
            dense_vecs = result["dense_vecs"]
            if hasattr(dense_vecs, "cpu"):
                dense_vecs = dense_vecs.cpu().numpy()
            embedding = dense_vecs[0].tolist()
            if any(math.isnan(x) or math.isinf(x) for x in embedding):
                logger.warning("检测到 NaN/Inf 嵌入，返回零向量")
                return [0.0] * len(embedding)
            return embedding
        except Exception as exc:
            logger.exception("生成嵌入失败，使用零向量")
            raise EmbeddingError(f"生成嵌入失败: {exc}") from exc

    def _get_query_embedding(self, query: str) -> List[float]:
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return self._get_query_embedding(query)

    def embed_text(self, text: str) -> List[float]:
        """对外暴露的文本向量化接口"""
        return self._get_text_embedding(text)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """批量向量化文本"""
        return [self._get_text_embedding(text) for text in texts]

    @classmethod
    def cleanup_all_instances(cls):
        """清理缓存的模型实例"""
        with _EMBEDDING_LOCK:
            for key, instance in list(_EMBEDDING_INSTANCES.items()):
                try:
                    if hasattr(instance, "model"):
                        del instance.model
                    logger.info("清理 BGE-M3 实例: %s", key)
                except Exception as exc:
                    logger.warning("清理实例失败 %s: %s", key, exc)
            _EMBEDDING_INSTANCES.clear()

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.info("GPU 缓存已清理")

    def get_memory_info(self) -> Dict:
        """查看当前内存/GPU 使用情况"""
        info = {
            "device": getattr(self, "_device", "cpu"),
            "model_path": getattr(self, "_model_path", ""),
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
        self.persist_base_dir = Path("./index_storage")

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

    def get_persist_dir(self, instance_id: int) -> Path:
        persist_dir = self.persist_base_dir / f"index_storage_{self.table_prefix}_{instance_id}"
        persist_dir.mkdir(parents=True, exist_ok=True)
        return persist_dir

    def upsert_chunks(self, chunks: List[TextNode], instance_id: int, embedding_model: BGEM3EmbeddingWrapper):
        try:
            vector_store = self._build_vector_store(instance_id)
            persist_dir = self.get_persist_dir(instance_id)

            storage_context = StorageContext.from_defaults(vector_store=vector_store, persist_dir=persist_dir)
            Settings.embed_model = embedding_model
            index = VectorStoreIndex.from_vector_store(
                vector_store,
                storage_context=storage_context,
                embed_model=embedding_model,
                show_progress=False,
            )
            index.insert_nodes(chunks)
            index.storage_context.persist(persist_dir=persist_dir)
            logger.info("成功写入 PGVector: %s 条", len(chunks))
        except Exception as exc:
            raise VectorStoreError(f"写入 PGVector 失败: {exc}") from exc

