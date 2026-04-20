"""
RAG 检索系统 - 使用 HTTP API 调用远程模型服务

该系统将嵌入模型和重排序模型部署在 Docker 容器中（通过 vLLM 等框架），
通过 HTTP API 进行调用，避免在本地加载大模型。

环境变量配置：
------------------
BGE_M3_API_URL: BGE-M3 嵌入模型 API 地址
    - 默认值: http://localhost:8000/v1/embeddings
    - 说明: 该服务应支持 OpenAI 兼容的 /v1/embeddings 端点
    - 请求格式: {"input": "text", "model": "bge-m3"}
    - 响应格式: {"data": [{"embedding": [...]}]} 或 {"embedding": [...]}

RERANKER_API_URL: 重排序模型 API 地址
    - 默认值: http://localhost:8001/v1/rerank
    - 说明: 该服务应接受查询和文档列表，返回重排序后的结果
    - 请求格式: {"query": "...", "documents": [...], "top_n": N, "model": "bge-reranker-v2-m3"}
    - 响应格式: {"results": [{"index": 0, "relevance_score": 0.9}]} 或 {"rankings": [...]}

使用示例：
------------------
# 方式1: 通过环境变量配置
export BGE_M3_API_URL="http://your-docker-host:8000/v1/embeddings"
export RERANKER_API_URL="http://your-docker-host:8001/v1/rerank"

"""

import os
import logging
from typing import List, Dict, Optional
from pathlib import Path
import requests
import numpy as np

from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from pydantic import Field

from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.core import VectorStoreIndex, StorageContext, load_index_from_storage
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.core import Settings

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BGEM3EmbeddingWrapper(BaseEmbedding):
    """BGE-M3 嵌入模型包装器 - 通过 HTTP API 调用远程服务"""
    api_url: str = Field(description="嵌入模型 API 地址")
    timeout: int = Field(default=30, description="请求超时时间（秒）")

    def __init__(self, api_url: str = None, timeout: int = 30):
        """
        初始化BGE-M3模型包装器
        
        Args:
            api_url: 嵌入模型 API 地址，如 "http://localhost:8000/v1/embeddings"
            timeout: 请求超时时间
        """
        if api_url is None:
            api_url = os.environ.get("BGE_M3_API_URL", "http://localhost:8000/v1/embeddings")
        
        super().__init__(api_url=api_url, timeout=timeout)
        logger.info(f"BGE-M3 嵌入模型 API: {api_url}")

    def _get_text_embedding(self, text: str) -> List[float]:
        """获取文本嵌入向量"""
        try:
            response = requests.post(
                self.api_url,
                json={
                    "input": text,
                    "model": "BAAI/bge-m3"
                },
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            
            # 兼容 OpenAI 格式和自定义格式
            if "data" in result and isinstance(result["data"], list) and len(result["data"]) > 0:
                # OpenAI 兼容格式: {"data": [{"embedding": [...]}]}
                return result["data"][0]["embedding"]
            elif "embedding" in result:
                # 自定义格式: {"embedding": [...]}
                return result["embedding"]
            elif "embeddings" in result:
                # 另一种格式: {"embeddings": [[...]]}
                return result["embeddings"][0] if isinstance(result["embeddings"][0], list) else result["embeddings"]
            else:
                logger.error(f"未知的响应格式: {result}")
                raise ValueError(f"无法解析嵌入向量响应: {result}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"调用嵌入模型 API 失败: {e}")
            raise
        except (KeyError, IndexError, ValueError) as e:
            logger.error(f"解析嵌入向量响应失败: {e}")
            raise

    def _get_query_embedding(self, query: str) -> List[float]:
        """获取查询嵌入向量"""
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        """异步获取查询嵌入向量"""
        return self._get_query_embedding(query)

    @classmethod
    def cleanup_all_instances(cls):
        """清理所有实例"""
        logger.info("HTTP API 模式无需清理资源")


class HTTPReranker(BaseNodePostprocessor):
    """基于 HTTP API 的重排序器"""
    
    api_url: str = Field(description="重排序模型 API 地址")
    top_n: int = Field(default=5, description="返回的最相关结果数量")
    timeout: int = Field(default=30, description="请求超时时间（秒）")
    
    def __init__(self, api_url: str = None, top_n: int = 5, timeout: int = 30):
        """
        初始化重排序器
        
        Args:
            api_url: 重排序模型 API 地址，如 "http://localhost:8001/v1/rerank"
            top_n: 返回的最相关结果数量
            timeout: 请求超时时间
        """
        if api_url is None:
            api_url = os.environ.get("RERANKER_API_URL", "http://localhost:8001/v1/rerank")
        
        super().__init__(api_url=api_url, top_n=top_n, timeout=timeout)
        logger.info(f"重排序模型 API: {api_url}")
    
    def _postprocess_nodes(
        self, nodes: List[NodeWithScore], query_bundle: Optional[QueryBundle] = None
    ) -> List[NodeWithScore]:
        """对检索到的节点进行重排序"""
        if not query_bundle or not nodes:
            return nodes
        
        query_str = query_bundle.query_str
        
        # 🔍 添加调试信息
        logger.info(f"🔍 Reranker 输入: {len(nodes)} 个节点, top_n={self.top_n}")
        
        try:
            # 准备文档列表
            documents = [node.node.get_content() for node in nodes]
            
            # 调用重排序 API
            response = requests.post(
                self.api_url,
                json={
                    "query": query_str,
                    "documents": documents,
                    "top_n": self.top_n,
                    "model": "BAAI/bge-reranker-v2-m3"
                },
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            
            # 🔍 记录 API 返回的结果数量
            if "results" in result:
                logger.info(f"🔍 Reranker API 返回了 {len(result['results'])} 个结果")
            elif "rankings" in result:
                logger.info(f"🔍 Reranker API 返回了 {len(result['rankings'])} 个结果")
            
            # 解析响应并重新排序节点
            # 兼容多种响应格式
            if "results" in result:
                # 格式1: {"results": [{"index": 0, "relevance_score": 0.9}, ...]}
                ranked_results = result["results"]
                reranked_nodes = []
                for item in ranked_results[:self.top_n]:
                    idx = item["index"]
                    score = item.get("relevance_score", item.get("score", nodes[idx].score))
                    node = nodes[idx]
                    node.score = score
                    reranked_nodes.append(node)
                logger.info(f"🔍 Reranker 输出: {len(reranked_nodes)} 个节点")
                return reranked_nodes
            elif "rankings" in result:
                # 格式2: {"rankings": [{"doc_index": 0, "score": 0.9}, ...]}
                ranked_results = result["rankings"]
                reranked_nodes = []
                for item in ranked_results[:self.top_n]:
                    idx = item["doc_index"]
                    score = item["score"]
                    node = nodes[idx]
                    node.score = score
                    reranked_nodes.append(node)
                logger.info(f"🔍 Reranker 输出: {len(reranked_nodes)} 个节点")
                return reranked_nodes
            else:
                logger.warning(f"未知的重排序响应格式: {result}，返回原始节点")
                return nodes[:self.top_n]
                
        except requests.exceptions.RequestException as e:
            logger.error(f"调用重排序 API 失败: {e}，返回原始节点")
            return nodes[:self.top_n]
        except (KeyError, IndexError, ValueError) as e:
            logger.error(f"解析重排序响应失败: {e}，返回原始节点")
            return nodes[:self.top_n]


class VectorStoreManager:
    """向量存储管理器"""

    def __init__(self, db_config: Dict, table_prefix: str = "doc_collection", engine=None):
        self.db_config = db_config
        self.table_prefix = table_prefix
        self.persist_base_dir = Path("./index_storage")
        self.vector_stores = {}
        self.engine = engine

    def get_persist_dir(self, instance_id: int) -> Path:
        """获取持久化目录"""
        collection_name = f"{self.table_prefix}_{instance_id}"
        persist_dir = self.persist_base_dir / f"index_storage_{collection_name}"
        persist_dir.mkdir(parents=True, exist_ok=True)
        return persist_dir

    def check_persist_exists(self, persist_dir: Path) -> bool:
        """检查持久化是否存在"""
        if not persist_dir.exists():
            return False
        required_files = ["docstore.json", "index_store.json"]
        return all((persist_dir / file_name).exists() for file_name in required_files)

    def create_vector_store(self, instance_id: int) -> PGVectorStore:
        """创建向量存储"""
        collection_name = f"{self.table_prefix}_{instance_id}"

        if collection_name in self.vector_stores:
            return self.vector_stores[collection_name]

        vector_store = PGVectorStore.from_params(
            database=self.db_config["database"],
            host=self.db_config["host"],
            password=self.db_config["password"],
            port=self.db_config["port"],
            user=self.db_config["user"],
            table_name=collection_name,
            embed_dim=1024,
        )

        self.vector_stores[collection_name] = vector_store
        return vector_store

    def create_index(self, instance_id: int, embed_model) -> VectorStoreIndex:
        """创建或加载向量索引"""
        vector_store = self.create_vector_store(instance_id)
        persist_dir = self.get_persist_dir(instance_id)

        try:
            if self.check_persist_exists(persist_dir):
                logger.info(f"从持久化存储加载索引: 实例 {instance_id}")
                storage_context = StorageContext.from_defaults(
                    vector_store=vector_store,
                    persist_dir=persist_dir
                )
                Settings.embed_model = embed_model
                return load_index_from_storage(storage_context, embed_model=embed_model)
            else:
                logger.info(f"创建新索引: 实例 {instance_id}")
                storage_context = StorageContext.from_defaults(vector_store=vector_store)
                return VectorStoreIndex.from_vector_store(
                    vector_store,
                    storage_context=storage_context,
                    embed_model=embed_model,
                    show_progress=True
                )
        except Exception as e:
            logger.warning(f"索引创建/加载失败，创建新索引: {e}")
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            return VectorStoreIndex.from_vector_store(
                vector_store,
                storage_context=storage_context,
                embed_model=embed_model,
                show_progress=True
            )

    def persist_index(self, index: VectorStoreIndex, instance_id: int):
        """持久化索引"""
        persist_dir = self.get_persist_dir(instance_id)
        try:
            index.storage_context.persist(persist_dir=persist_dir)
            logger.info(f"索引已持久化: 实例 {instance_id} -> {persist_dir}")
        except Exception as e:
            logger.error(f"持久化失败: 实例 {instance_id}, 错误: {e}")
            raise

    def list_persisted_instances(self) -> List[int]:
        """列出所有已持久化的实例ID"""
        persisted_instances = []
        if not self.persist_base_dir.exists():
            return persisted_instances

        for item in self.persist_base_dir.iterdir():
            if item.is_dir() and item.name.startswith(f"index_storage_{self.table_prefix}_"):
                try:
                    instance_id = int(item.name.split("_")[-1])
                    if self.check_persist_exists(item):
                        persisted_instances.append(instance_id)
                except (ValueError, IndexError):
                    continue

        return sorted(persisted_instances)

    def list_available_collections(self) -> List[str]:
        """列出数据库中所有可用的向量存储表"""
        try:
            query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name LIKE :pattern
            """
            with self.engine.connect() as conn:
                result = conn.execute(text(query), {"pattern": f"data_{self.table_prefix}_%"})
                tables = [row[0] for row in result.fetchall()]
            logger.info(f"找到 {len(tables)} 个向量存储表")
            return tables
        except Exception as e:
            logger.error(f"获取向量存储表列表失败: {e}")
            return []

    def drop_vector_store(self, instance_id: int):
        """删除向量存储表"""
        collection_name = f"data_{self.table_prefix}_{instance_id}"
        logger.info(f"删除向量存储表: {collection_name}")
        sql = f'DROP TABLE IF EXISTS {collection_name}'
        try:
            with self.engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as e:
            logger.error(f"删除向量表时出错: {e}", exc_info=True)


class RAGRetrieverSystem:
    """RAG检索系统"""

    def __init__(
            self,
            POSTGRES_SERVER: str,
            POSTGRES_USER: str,
            POSTGRES_PASSWORD: str,
            POSTGRES_DB: str,
            POSTGRES_PORT: int,
            table_prefix: str = "doc_collection",
            instance_id: int = 1,
            bge_m3_api_url: str = None,
            reranker_api_url: str = None,
            default_top_k: int = 10,
            default_top_n: int = 5,
    ):
        # 数据库配置
        self.db_config = {
            "host": POSTGRES_SERVER,
            "user": POSTGRES_USER,
            "password": POSTGRES_PASSWORD,
            "database": POSTGRES_DB,
            "port": POSTGRES_PORT
        }

        # 系统配置
        self.instance_id = instance_id
        self.table_prefix = table_prefix
        
        # API 配置
        self.bge_m3_api_url = bge_m3_api_url or os.environ.get("BGE_M3_API_URL", "http://localhost:8000/v1/embeddings")
        self.reranker_api_url = reranker_api_url or os.environ.get("RERANKER_API_URL", "http://localhost:8001/v1/rerank")
        
        # 检索参数配置
        self.default_top_k = default_top_k
        self.default_top_n = default_top_n
        logger.info(f"检索参数配置 - top_k: {default_top_k}, top_n: {default_top_n}")

        # 🔧 配置全局参数（仅做检索，不使用 LLM）
        Settings.llm = None  # 禁用 LLM
        Settings.context_window = 8192  # 设置上下文窗口大小
        Settings.num_output = 512  # 设置输出 token 数量
        logger.info("已配置检索模式（禁用 LLM，仅做向量检索）")

        # 初始化核心组件
        self.embedding_model = self._init_embedding_model()
        self.reranker = self._init_reranker()
        self._init_database()
        self.vector_store_manager = VectorStoreManager(self.db_config, table_prefix, engine=self.engine)

    def _init_embedding_model(self) -> BGEM3EmbeddingWrapper:
        """初始化嵌入模型 - 使用 HTTP API"""
        logger.info("正在初始化 BGE-M3 嵌入模型 API 连接...")
        try:
            embedding_model = BGEM3EmbeddingWrapper(api_url=self.bge_m3_api_url)
            logger.info(f"BGE-M3 API 连接初始化完成: {self.bge_m3_api_url}")
            return embedding_model
        except Exception as e:
            logger.error(f"嵌入模型 API 初始化失败: {e}")
            raise

    def _init_reranker(self) -> HTTPReranker:
        """初始化重排序器 - 使用 HTTP API"""
        logger.info("正在初始化重排序器 API 连接...")
        try:
            reranker = HTTPReranker(
                api_url=self.reranker_api_url,
                top_n=self.default_top_n,
                timeout=30
            )
            logger.info(f"重排序器 API 连接初始化完成: {self.reranker_api_url}")
            return reranker
        except Exception as e:
            logger.error(f"重排序器 API 初始化失败: {e}")
            raise

    def _init_database(self):
        """初始化数据库连接"""
        connection_string = (
            f"postgresql://{self.db_config['user']}:{self.db_config['password']}"
            f"@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
        )
        self.engine = create_engine(
            connection_string,
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=5,
            pool_timeout=30
        )

    def get_retriever_for_collection(self, collection_name: str, embedding_model=None, top_k: int = None):
        """
        通过指定的表名(collection_name)从持久化存储获取对应的检索器

        Args:
            collection_name: 向量存储表名，如 "doc_collection_1"
            embedding_model: 可选的嵌入模型，不指定时使用当前系统的模型
            top_k: 检索的最大结果数量（不指定时使用实例化时的默认值）

        Returns:
            检索器对象列表
        """
        if top_k is None:
            top_k = self.default_top_k
        try:
            if embedding_model is None:
                embedding_model = self.embedding_model

            # 从collection_name提取instance_id
            try:
                instance_id = int(collection_name.split('_')[-1])
            except (ValueError, IndexError):
                logger.warning(f"无法从表名 {collection_name} 提取实例ID")
                instance_id = None

            # 创建向量存储
            vector_store = PGVectorStore.from_params(
                database=self.db_config["database"],
                host=self.db_config["host"],
                password=self.db_config["password"],
                port=self.db_config["port"],
                user=self.db_config["user"],
                table_name=collection_name,
                embed_dim=1024,
            )

            # 直接从 PGVector 创建索引（向量已存储在数据库中，无需本地持久化）
            logger.info(f"从 PGVector 创建索引: {collection_name}")
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            index = VectorStoreIndex.from_vector_store(
                vector_store,
                storage_context=storage_context,
                embed_model=embedding_model,
                show_progress=False
            )

            # 返回检索器
            retriever = index.as_retriever(similarity_top_k=top_k)
            logger.info(f"成功创建检索器，表名: {collection_name}")
            return retriever

        except Exception as e:
            logger.error(f"创建检索器失败，表名: {collection_name}, 错误: {e}")
            raise

    def get_retriever_by_instance_id(self, instance_id: int, top_k: int = None):
        """
        通过实例ID获取检索器（便捷方法）

        Args:
            instance_id: 知识库实例ID
            top_k: 检索的最大结果数量（不指定时使用实例化时的默认值）

        Returns:
            检索器对象
        """
        if top_k is None:
            top_k = self.default_top_k
        collection_name = f"{self.table_prefix}_{instance_id}"
        return self.get_retriever_for_collection(collection_name, top_k=top_k)

    def get_query_engine_for_collection(self, collection_name: str, embedding_model=None, top_k: int = None, 
                                       use_reranker: bool = True, reranker_top_n: int = None):
        """
        根据指定表名(collection_name)动态创建query engine

        Args:
            collection_name: 向量存储表名
            embedding_model: 嵌入模型
            top_k: 检索数量（不指定时使用实例化时的默认值）
            use_reranker: 是否使用重排序
            reranker_top_n: 重排序后返回的结果数量（不指定时使用实例化时的默认值）

        Returns:
            QueryEngine对象
        """
        try:
            if embedding_model is None:
                embedding_model = self.embedding_model
            
            if top_k is None:
                top_k = self.default_top_k
            
            if reranker_top_n is None:
                reranker_top_n = self.default_top_n

            retriever = self.get_retriever_for_collection(collection_name, embedding_model=embedding_model, top_k=top_k)

            # 创建 QueryEngine（不使用 LLM 生成，只返回检索结果）
            if use_reranker and self.reranker:
                # 如果需要使用不同的 top_n，创建新的 reranker 实例
                if reranker_top_n != self.default_top_n:
                    reranker = HTTPReranker(
                        api_url=self.reranker_api_url,
                        top_n=min(reranker_top_n, top_k)
                    )
                else:
                    # 使用预初始化的 reranker
                    reranker = self.reranker
                return RetrieverQueryEngine.from_args(
                    retriever=retriever,
                    node_postprocessors=[reranker],
                    streaming=False,  # 禁用流式输出
                )
            else:
                return RetrieverQueryEngine.from_args(
                    retriever=retriever,
                    streaming=False,  # 禁用流式输出
                )

        except Exception as e:
            logger.error(f"创建Query Engine失败: {e}")
            raise

    def list_available_collections(self) -> List[str]:
        """列出数据库中所有可用的向量存储表"""
        return self.vector_store_manager.list_available_collections()

    def list_persisted_collections(self) -> List[str]:
        """获取所有已持久化的collection列表"""
        persisted_instances = self.vector_store_manager.list_persisted_instances()
        return [f"{self.table_prefix}_{instance_id}" for instance_id in persisted_instances]

    def get_all_retrievers(self, embedding_model=None, top_k: int = None) -> Dict[str, any]:
        """
        获取所有向量表的检索器

        Args:
            embedding_model: 可选的嵌入模型
            top_k: 检索的最大结果数量（不指定时使用实例化时的默认值）

        Returns:
            Dict: 键为collection_name，值为retriever对象
        """
        try:
            if embedding_model is None:
                embedding_model = self.embedding_model
            
            if top_k is None:
                top_k = self.default_top_k

            collection_names = self.vector_store_manager.list_available_collections()
            retrievers = {}

            for collection_name in collection_names:
                # 移除 "data_" 前缀（如果有）
                clean_name = collection_name.replace("data_", "")
                try:
                    retriever = self.get_retriever_for_collection(clean_name, embedding_model, top_k)
                    retrievers[clean_name] = retriever
                    logger.info(f"成功创建检索器: {clean_name}")
                except Exception as e:
                    logger.warning(f"为表 {clean_name} 创建检索器失败: {e}")

            return retrievers

        except Exception as e:
            logger.error(f"创建统一检索器失败: {e}")
            raise

    def cleanup(self, silent=False):
        """
        清理资源
        
        Args:
            silent: 是否静默模式（不记录日志），用于析构函数调用
        """
        try:
            if not silent:
                logger.info("开始清理RAG系统资源...")

            # 清理数据库连接
            if hasattr(self, 'engine') and self.engine:
                self.engine.dispose()
                if not silent:
                    logger.info("数据库连接已清理")

            if not silent:
                logger.info("RAG系统资源清理完成")

        except Exception as e:
            # 静默模式下不记录日志（避免 Python 关闭时的错误）
            if not silent:
                try:
                    logger.warning(f"清理资源时出错: {e}")
                except:
                    pass  # 如果 logger 已经被销毁，忽略

    def __del__(self):
        """
        析构函数 - 在对象销毁时自动调用
        
        注意：使用 silent=True 避免 Python 关闭时的 logging 错误
        """
        try:
            # 检查 Python 是否正在关闭
            import sys
            if sys is None or sys.meta_path is None:
                # Python 正在关闭，静默清理
                return
            
            # 静默清理（不记录日志）
            self.cleanup(silent=True)
        except:
            # 完全捕获所有异常，避免析构函数中的错误
            pass


# ==================== 便捷函数 ====================

def create_rag_retriever_system(
        host: str = "localhost",
        user: str = "postgres",
        password: str = "change_me_pg_password",
        database: str = "postgres",
        port: int = 5432,
        table_prefix: str = "doc_collection",
        instance_id: int = 1,
        bge_m3_api_url: str = None,
        reranker_api_url: str = None,
        default_top_k: int = 10,
        default_top_n: int = 5
) -> RAGRetrieverSystem:
    """
    便捷函数：快速创建RAG检索系统

    Args:
        host: 数据库主机
        user: 数据库用户
        password: 数据库密码
        database: 数据库名
        port: 数据库端口
        table_prefix: 表前缀
        instance_id: 实例ID
        bge_m3_api_url: BGE-M3 嵌入模型 API 地址（默认从环境变量 BGE_M3_API_URL 读取）
        reranker_api_url: 重排序模型 API 地址（默认从环境变量 RERANKER_API_URL 读取）
        default_top_k: 默认的向量检索数量（粗排阶段），默认 10
        default_top_n: 默认的重排序返回数量（精排阶段），默认 5

    Returns:
        RAGRetrieverSystem实例
    """
    return RAGRetrieverSystem(
        POSTGRES_SERVER=host,
        POSTGRES_USER=user,
        POSTGRES_PASSWORD=password,
        POSTGRES_DB=database,
        POSTGRES_PORT=port,
        table_prefix=table_prefix,
        instance_id=instance_id,
        bge_m3_api_url=bge_m3_api_url,
        reranker_api_url=reranker_api_url,
        default_top_k=default_top_k,
        default_top_n=default_top_n
    )


# ==================== 使用示例 ====================
if __name__ == "__main__":
    # 禁用LLM，仅做检索
    Settings.llm = None

    # 创建RAG检索系统，设置默认的 top_k 和 top_n
    rag_system = create_rag_retriever_system(
        host="localhost",
        user="postgres",
        password="change_me_pg_password",
        database="postgres",
        port=5432,
        table_prefix="doc_collection",
        instance_id=1,
        default_top_k=20,  # 设置默认粗排检索数量
        default_top_n=3    # 设置默认精排返回数量
    )

    try:
        # 示例1: 使用默认的 top_k 值
        retriever = rag_system.get_retriever_by_instance_id(instance_id=1)
        results = retriever.retrieve("你的查询问题")
        print("检索结果:", results)

        # 示例2: 覆盖默认值，使用自定义 top_k
        retriever_custom = rag_system.get_retriever_by_instance_id(instance_id=1, top_k=30)
        results_custom = retriever_custom.retrieve("你的查询问题")
        print("自定义检索结果:", results_custom)

        # 示例3: 使用默认值的 query engine（带重排序）
        query_engine = rag_system.get_query_engine_for_collection(
            collection_name="doc_collection_1",
            use_reranker=True
        )
        response = query_engine.query("你的查询问题")
        print("查询响应:", response)

        # 示例4: 覆盖默认值的 query engine
        query_engine_custom = rag_system.get_query_engine_for_collection(
            collection_name="doc_collection_1",
            top_k=50,            # 粗排检索 50 个
            use_reranker=True,
            reranker_top_n=10    # 精排返回 10 个
        )
        response_custom = query_engine_custom.query("你的查询问题")
        print("自定义查询响应:", response_custom)

        # 示例5: 列出所有可用的collections
        collections = rag_system.list_available_collections()
        print("可用的collections:", collections)

        # 示例6: 获取所有检索器（使用默认 top_k）
        all_retrievers = rag_system.get_all_retrievers()
        print("所有检索器:", all_retrievers.keys())

    finally:
        # 清理资源
        rag_system.cleanup()

