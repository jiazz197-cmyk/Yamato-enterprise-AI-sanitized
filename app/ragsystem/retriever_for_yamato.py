# from app.integrations.for_dify.dify_config import *
import gc
import os
import threading
from typing import Optional, Dict, List

from llama_index.core.query_engine import RetrieverQueryEngine

from app.core.storage import download_from_minio
from app.ragsystem.data_analyze import excel_to_json
from app.ragsystem.RAGretriever import create_rag_retriever_system, HTTPReranker


def format_docs(docs):
    return "\n\n".join(f"{doc.page_content}" for doc in docs)


class ModelManager:
    """单例模式管理模型实例，避免重复加载"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._rag_system = None
        self._reranker = None
        self._retrievers_cache = {}
        self._query_engines_cache = {}
        self._reranker_api_url = os.environ.get("RERANKER_API_URL", "http://localhost:8001/v1/rerank")
        self._initialized = True
        print(f"模型管理器初始化完成，使用 HTTP API 模式")
    
    def set_rag_system(self, rag_system):
        """设置RAG系统实例"""
        if self._rag_system is None:
            self._rag_system = rag_system
            print("RAG系统已设置到模型管理器")
        else:
            print("RAG系统已存在，跳过重复设置")
    
    def get_reranker(self):
        """获取重排序器实例（单例）"""
        if self._reranker is None:
            try:
                self._reranker = HTTPReranker(
                    api_url=self._reranker_api_url,
                    top_n=3,
                    timeout=30
                )
                print(f"重排序器创建完成，API: {self._reranker_api_url}")
            except Exception as e:
                print(f"创建重排序器失败: {e}")
                self._reranker = None
        return self._reranker
    
    def get_retriever(self, collection_name: str, top_k: int = 5):
        """获取检索器（带缓存）"""
        cache_key = f"{collection_name}_{top_k}"
        
        if cache_key not in self._retrievers_cache:
            if self._rag_system is None:
                raise ValueError("RAG系统未设置")
            
            try:
                retriever = self._rag_system.get_retriever_for_collection(collection_name, top_k=top_k)
                self._retrievers_cache[cache_key] = retriever
                print(f"检索器缓存: {collection_name}")
            except Exception as e:
                print(f"创建检索器失败 {collection_name}: {e}")
                return None
        
        return self._retrievers_cache.get(cache_key)
    
    def get_query_engine(self, collection_name: str, top_k: int = 5):
        """获取查询引擎（带缓存）"""
        cache_key = f"{collection_name}_{top_k}"
        
        if cache_key not in self._query_engines_cache:
            retriever = self.get_retriever(collection_name, top_k)
            if retriever is None:
                return None
            
            reranker = self.get_reranker()
            
            try:
                query_engine = RetrieverQueryEngine.from_args(
                    retriever=retriever,
                    node_postprocessors=[reranker] if reranker else [],
                )
                self._query_engines_cache[cache_key] = query_engine
                print(f"查询引擎缓存: {collection_name}")
            except Exception as e:
                print(f"创建查询引擎失败 {collection_name}: {e}")
                return None
        
        return self._query_engines_cache.get(cache_key)
    
    def get_available_collections(self) -> List[str]:
        """获取可用的collection列表"""
        if self._rag_system is None:
            return []
        
        try:
            collections = self._rag_system.vector_store_manager.list_available_collections()
            # 去掉"data_"前缀
            return [col.replace("data_", "") for col in collections]
        except Exception as e:
            print(f"获取collection列表失败: {e}")
            return []
    
    def clear_cache(self):
        """清理缓存"""
        print("开始清理模型管理器缓存...")
        self._retrievers_cache.clear()
        self._query_engines_cache.clear()
        
        # 强制垃圾回收
        gc.collect()
        print("缓存清理完成")
    
    def get_memory_info(self) -> Dict:
        """获取内存使用信息"""
        info = {
            "mode": "HTTP API",
            "retrievers_cached": len(self._retrievers_cache),
            "query_engines_cached": len(self._query_engines_cache),
            "reranker_api_url": self._reranker_api_url,
        }
        
        return info


class OptimizedRetriever:
    """优化的检索器，使用单例模式管理资源"""
    
    def __init__(self, rag_system=None, collection_name: Optional[str] = None):
        self.collection_name = collection_name
        
        if rag_system is None:
            raise ValueError("rag_system is required")
        
        # 获取模型管理器实例
        self.model_manager = ModelManager()
        self.model_manager.set_rag_system(rag_system)
        
        # 初始化查询引擎
        self._initialize_query_engines()
    
    def _initialize_query_engines(self):
        """初始化查询引擎"""
        if self.collection_name is None:
            # 全库检索模式：获取所有可用collections
            collections = self.model_manager.get_available_collections()
            print(f"初始化全库检索，发现 {len(collections)} 个collection")
            
            self.query_engines = {}
            # 只为真正需要的collection创建query_engine，延迟加载
            self.available_collections = collections
        else:
            # 单库检索模式
            query_engine = self.model_manager.get_query_engine(self.collection_name, top_k=5)
            if query_engine is None:
                raise ValueError(f"无法创建查询引擎: {self.collection_name}")
            self.query_engines = query_engine
            print(f"单库检索模式初始化完成: {self.collection_name}")
    
    def get_response(self, question: str, max_collections: int = 3) -> dict:
        """获取检索响应"""
        try:
            if self.collection_name is None:
                return self._get_multi_collection_response(question, max_collections)
            else:
                return self._get_single_collection_response(question)
        except Exception as e:
            print(f"检索响应失败: {e}")
            return {
                "content": [f"检索失败: {str(e)}"],
                "source": ["error"]
            }
    
    def _get_single_collection_response(self, question: str) -> dict:
        """单库检索响应"""
        raw_docs = self.query_engines.query(question)
        source_nodes = raw_docs.source_nodes
        
        sources = []
        contents = []
        
        for node in source_nodes:
            source = node.metadata.get('source', 'Unknown')
            content = node.text.strip()
            sources.append(source)
            contents.append(content)
        
        return {
            "content": contents[:5],
            "source": sources[:5]
        }
    
    def _get_multi_collection_response(self, question: str, max_collections: int) -> dict:
        """多库检索响应（优化版）"""
        all_contents = []
        all_sources = []
        
        # 限制查询的collection数量，避免资源过度消耗
        collections_to_query = self.available_collections[:max_collections]
        
        for collection_name in collections_to_query:
            try:
                # 延迟创建query_engine
                if collection_name not in self.query_engines:
                    query_engine = self.model_manager.get_query_engine(collection_name, top_k=3)
                    if query_engine is not None:
                        self.query_engines[collection_name] = query_engine
                    else:
                        continue
                
                query_engine = self.query_engines[collection_name]
                raw_docs = query_engine.query(question)
                source_nodes = raw_docs.source_nodes
                
                for node in source_nodes[:2]:  # 每个collection最多取2个结果
                    source = node.metadata.get('source', f'Unknown_{collection_name}')
                    content = node.text.strip()
                    all_sources.append(source)
                    all_contents.append(content)
                    
            except Exception as e:
                print(f"查询collection {collection_name} 失败: {e}")
                continue
        
        return {
            "content": all_contents[:5],
            "source": all_sources[:5]
        }
    
    def get_charts(self, question: str):
        """获取图表数据"""
        try:
            response_filename = self.get_response(question)
            filename = response_filename["source"]
            
            if not filename or filename == ["error"]:
                return {"error": "未找到相关文件"}
            
            file_path = download_from_minio(filename[0] if isinstance(filename, list) else filename)
            data_source = excel_to_json(file_path)
            return data_source
        except Exception as e:
            print(f"获取图表数据失败: {e}")
            return {"error": str(e)}
    
    def cleanup(self):
        """清理资源"""
        print("开始清理retriever资源...")
        if hasattr(self, 'query_engines'):
            if isinstance(self.query_engines, dict):
                self.query_engines.clear()
            else:
                del self.query_engines
        
        # 清理模型管理器缓存
        self.model_manager.clear_cache()
        
        print("Retriever资源清理完成")
    
    def get_memory_info(self) -> Dict:
        """获取内存使用信息"""
        return self.model_manager.get_memory_info()
    
    def __del__(self):
        """析构函数"""
        try:
            self.cleanup()
        except:
            pass


# 为了向后兼容，保留原来的类名
class retriever(OptimizedRetriever):
    """向后兼容的类名别名"""
    pass


# 全局清理函数
def cleanup_all_resources():
    """清理所有资源的全局函数"""
    try:
        manager = ModelManager()
        manager.clear_cache()
        print("全局资源清理完成")
    except Exception as e:
        print(f"全局资源清理失败: {e}")


if __name__ == '__main__':
    try:
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
        # 这里需要传入实际的rag_system实例
        retriever_instance = OptimizedRetriever(rag_system=rag_system)
        responses = retriever_instance.get_response("北部湾")
        print(responses)
        
        # 显示内存信息
        print("内存使用情况:", retriever_instance.get_memory_info())
        
        print("请确保传入有效的rag_system实例")
        
    except Exception as e:
        print(f"执行失败: {e}")
    finally:
        # 清理资源
        cleanup_all_resources()

