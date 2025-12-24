import logging
import os
from typing import List, Optional

import torch
from transformers import AutoTokenizer, pipeline
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sklearn.feature_extraction.text import CountVectorizer

try:
    from keybert import KeyBERT

    KEYBERT_AVAILABLE = True
except ImportError:
    KeyBERT = None
    KEYBERT_AVAILABLE = False

from .exceptions import EmbeddingError, TextSplitError

logger = logging.getLogger(__name__)


class TagGenerator:
    """负责从文本中提取关键词标签"""

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2", device: str = "auto"):
        try:
            # 从环境变量读取 GPU 设备配置
            gpu_device_id = int(os.environ.get("LOCAL_MODEL_GPU_DEVICE", "0"))
            
            if device == "auto":
                if torch.cuda.is_available():
                    self.device = f"cuda:{gpu_device_id}"
                    logger.info(f"TagGenerator 将使用 GPU:{gpu_device_id}")
                else:
                    self.device = "cpu"
                    logger.info("TagGenerator 将使用 CPU（CUDA 不可用）")
            else:
                self.device = device

            if KEYBERT_AVAILABLE:
                try:
                    self.keyword_model = KeyBERT(model=model_name)
                except Exception:
                    logger.warning("KeyBERT 指定模型加载失败，尝试默认模型", exc_info=True)
                    self.keyword_model = KeyBERT()
            else:
                self.keyword_model = None

            try:
                # pipeline 使用指定的 GPU 设备
                pipeline_device = gpu_device_id if self.device.startswith("cuda") else -1
                self.keyphrase_model = pipeline(
                    "token-classification",
                    model="ml6team/keyphrase-extraction-kbir-inspec",
                    device=pipeline_device,
                )
                if pipeline_device >= 0:
                    logger.info(f"Keyphrase pipeline 使用 GPU:{pipeline_device}")
            except Exception:
                logger.warning("Keyphrase pipeline 加载失败，将跳过备用模型", exc_info=True)
                self.keyphrase_model = None
        except Exception as exc:
            raise EmbeddingError(f"初始化 TagGenerator 失败: {exc}") from exc

    def extract_tags(self, text: str, num_tags: int = 5, diversity: float = 0.5) -> List[str]:
        if not text.strip():
            return []

        tags: List[str] = []
        try:
            if self.keyword_model is not None:
                keywords = self.keyword_model.extract_keywords(
                    text,
                    keyphrase_ngram_range=(1, 2),
                    stop_words=None,
                    top_n=num_tags * 2,
                    use_mmr=True,
                    diversity=diversity,
                )
                tags = [kw[0] for kw in keywords if kw[1] > 0.2]

            if len(tags) < num_tags and self.keyphrase_model is not None:
                additional_tags = list(
                    {
                        item["word"]
                        for item in self.keyphrase_model(text)
                        if item.get("score", 0) > 0.3
                    }
                )
                tags.extend(additional_tags)
                tags = list(set(tags))

            if len(tags) < num_tags:
                tags.extend(self._extract_simple_tags(text, num_tags - len(tags)))
            return tags[:num_tags]
        except Exception as exc:
            logger.warning("标签生成失败，使用降级策略: %s", exc, exc_info=True)
            return self._extract_simple_tags(text, num_tags)

    def _extract_simple_tags(self, text: str, num_tags: int) -> List[str]:
        try:
            vectorizer = CountVectorizer(max_features=num_tags * 2, stop_words=None, ngram_range=(1, 2))
            X = vectorizer.fit_transform([text])
            feature_names = vectorizer.get_feature_names_out()
            word_counts = X.toarray()[0]
            word_freq = dict(zip(feature_names, word_counts))
            sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
            return [word for word, _ in sorted_words[:num_tags]]
        except Exception:
            logger.exception("简单标签提取失败")
            return []


class TokenAwareTextSplitter:
    """基于 token 计数的文本切分器"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50, model_name: Optional[str] = None):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._init_tokenizer(model_name)

    def _init_tokenizer(self, model_name: Optional[str]):
        try:
            # 不再依赖本地 ai_models 目录，统一通过模型名加载 tokenizer
            if model_name is None:
                # 可通过环境变量覆盖默认模型名
                model_name = os.environ.get("BGE_M3_TOKENIZER_NAME", "BAAI/bge-m3")

            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        except Exception as exc:
            raise TextSplitError(f"初始化 tokenizer 失败: {exc}") from exc

    def count_tokens(self, text: str) -> int:
        try:
            return len(self.tokenizer.encode(text, add_special_tokens=False))
        except Exception as exc:
            raise TextSplitError(f"统计 token 失败: {exc}") from exc

    def split_text(self, text: str) -> List[str]:
        if not text.strip():
            return [""]

        try:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                length_function=self.count_tokens,
                separators=["\n\n", "\n", "。", "．", "。 ", "\\.\\s+", "！", "？", "；", "…", " ", ""],
            )
            return splitter.split_text(text)
        except Exception as exc:
            raise TextSplitError(f"文本切分失败: {exc}") from exc

