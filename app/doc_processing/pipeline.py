import logging
import os
import uuid
from io import BytesIO
from typing import Dict, List, Optional, Union

from llama_index.core.schema import TextNode

from .doc_reader import DocumentProcessor
from .embedding_store import BGEM3EmbeddingWrapper, VectorStoreManager
from .exceptions import DocumentProcessingError
from .text_splitter import TagGenerator, TokenAwareTextSplitter

logger = logging.getLogger(__name__)


FileInput = Union[str, os.PathLike, BytesIO]


class DocumentProcessingPipeline:
    """从文档到 PGVector 的最小可复用处理管线"""

    def __init__(
        self,
        db_config: Dict,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        table_prefix: str = "doc_collection",
        device: str = "auto",
        num_tags: int = 5,
    ):
        self.db_config = db_config
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.table_prefix = table_prefix
        self.num_tags = num_tags

        self.text_splitter = TokenAwareTextSplitter(chunk_size, chunk_overlap)
        self.tag_generator = TagGenerator(device=device)
        self.document_processor = DocumentProcessor()
        self.embedding_model = BGEM3EmbeddingWrapper(device=device)
        self.vector_store_manager = VectorStoreManager(db_config, table_prefix=table_prefix)

    def _prepare_files(self, input_data: Union[FileInput, List[FileInput]]) -> List[FileInput]:
        if isinstance(input_data, (str, os.PathLike)):
            if os.path.isfile(input_data):
                return [str(input_data)]
            if os.path.isdir(input_data):
                allowed_ext = set(self.document_processor.parsers.keys())
                collected = []
                for root, _, files in os.walk(input_data):
                    for filename in files:
                        if filename.lower().split(".")[-1] in allowed_ext:
                            collected.append(os.path.join(root, filename))
                return collected
            logger.warning("指定路径不存在: %s", input_data)
            return []
        if isinstance(input_data, BytesIO):
            return [input_data]
        if isinstance(input_data, list):
            return input_data
        raise ValueError("input_data 只支持路径、数据流或它们的列表")

    def _documents_to_nodes(self, documents: List, instance_id: int) -> List[TextNode]:
        nodes = []
        for chunk in documents:
            metadata = dict(chunk.metadata)
            metadata.setdefault("chunk_id", str(uuid.uuid4()))
            metadata["instance_id"] = instance_id
            node = TextNode(
                text=chunk.page_content,
                metadata=metadata,
            )
            nodes.append(node)
        return nodes

    def process(
        self,
        input_data: Union[FileInput, List[FileInput]],
        instance_id: int = 1,
    ):
        """主入口：读取、切分、向量化并写入 PGVector"""
        files = self._prepare_files(input_data)
        if not files:
            logger.warning("未找到可处理的文件")
            return {"status": "empty"}

        processed = 0
        for file_path in files:
            try:
                chunks = self.document_processor.process_document(
                    file_path,
                    self.text_splitter,
                    tag_generator=self.tag_generator,
                    num_tags=self.num_tags,
                )
                if not chunks:
                    continue
                nodes = self._documents_to_nodes(chunks, instance_id)
                self.vector_store_manager.upsert_chunks(nodes, instance_id, self.embedding_model)
                processed += 1
            except DocumentProcessingError as exc:
                logger.error("处理文件失败 %s: %s", file_path, exc)
        return {"status": "success", "processed_files": processed, "total_files": len(files)}

