"""
文档处理功能模块使用示例 (Demo)

本文件展示批量数据流处理的使用方法：
1. 从本地文件转换为数据流（使用 collect_streams_from_path）
2. 批量处理多个数据流
"""

from __future__ import annotations

import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Dict, List

from app.core.config import settings
from app.core.logging import setup_logging
from app.doc_processing import DocumentProcessingPipeline

# 初始化日志
setup_logging()
logger = logging.getLogger(__name__)


def build_db_config() -> Dict[str, str | int]:
    """
    构造数据库配置
    
    Returns:
        数据库配置字典
    """
    return {
        "host": settings.POSTGRES_SERVER,
        "user": settings.POSTGRES_USER,
        "password": settings.POSTGRES_PASSWORD,
        "database": settings.POSTGRES_DB,
        "port": settings.POSTGRES_PORT,
    }


def collect_streams_from_path(input_path: str | os.PathLike) -> List[BytesIO]:
    """
    支持单文件或目录批量转换为数据流列表。
    生成的数据流格式与 MinIO 数据流格式一致。
    
    Args:
        input_path: 本地文件或目录路径
    
    Returns:
        List[BytesIO]: 数据流列表，每个流都带有 name 属性
    """
    # 支持的文件扩展名列表
    supported_extensions = {"pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "html", "htm", "json", "txt", "md"}
    
    # 需要跳过的系统文件
    skip_files = {".DS_Store", "Thumbs.db", ".gitignore", ".gitkeep"}
    
    path = Path(input_path)
    if path.is_file():
        # 单文件：检查扩展名
        file_name = path.name
        if file_name in skip_files:
            logger.warning(f"跳过系统文件: {file_name}")
            return []
        ext = path.suffix[1:].lower() if path.suffix else ""
        if ext not in supported_extensions:
            logger.warning(f"跳过不支持的文件类型: {file_name} (扩展名: {ext})")
            return []
        
        # 转换为数据流
        stream = BytesIO()
        with open(path, "rb") as src:
            stream.write(src.read())
        stream.seek(0)
        stream.name = path.name
        return [stream]
    
    if path.is_dir():
        streams: List[BytesIO] = []
        for file in sorted(path.rglob("*")):
            if not file.is_file():
                continue
            
            file_name = file.name
            
            # 跳过系统文件
            if file_name in skip_files:
                logger.debug(f"跳过系统文件: {file_name}")
                continue
            
            # 检查文件扩展名
            ext = file.suffix[1:].lower() if file.suffix else ""
            if ext not in supported_extensions:
                logger.debug(f"跳过不支持的文件类型: {file_name} (扩展名: {ext})")
                continue
            
            # 转换为数据流
            stream = BytesIO()
            with open(file, "rb") as src:
                stream.write(src.read())
            stream.seek(0)
            stream.name = file.name
            streams.append(stream)
        
        logger.info(f"从本地路径共加载 {len(streams)} 个文件: {input_path}")
        return streams
    
    raise FileNotFoundError(f"输入路径不存在: {input_path}")


# ============================================================================
# 示例: 批量数据流处理
# ============================================================================
def example_batch_stream_processing():
    """
    批量数据流处理示例
    
    此示例展示如何：
    1. 从本地文件转换为数据流（使用 collect_streams_from_path）
    2. 批量处理多个数据流
    3. 将结果上传到 PGVector
    """
    print("\n" + "="*60)
    print("批量数据流处理示例")
    print("="*60)
    
    # 步骤 1: 准备数据库配置
    db_config = build_db_config()
    
    # 步骤 2: 创建处理管线
    pipeline = DocumentProcessingPipeline(db_config=db_config)
    
    # 步骤 3: 从本地文件转换为数据流
    input_path = "/path/to/your/documents"  # 实际目录路径
    streams = collect_streams_from_path(input_path) # ！！！！！这里可以换成minio数据！！！！！！！！
    
    # 步骤 4: 批量处理数据流
    if streams:
        print(f"\n准备处理 {len(streams)} 个数据流...")
        
        # 验证数据流格式（可选）
        for i, stream in enumerate(streams):
            if not hasattr(stream, "name") or not stream.name:
                logger.warning(f"警告: 数据流 {i} 缺少 name 属性")
            else:
                logger.debug(f"数据流 {i}: {stream.name}")
        
        try:
            result = pipeline.process(
                input_data=streams,  # 传入 BytesIO 对象列表
                instance_id=1,       # 知识实例 ID
            )
            
            print(f"\n处理结果:")
            print(f"  - 状态: {result.get('status')}")
            print(f"  - 成功处理: {result.get('processed_files', 0)} 个文件")
            print(f"  - 总计文件: {result.get('total_files', 0)} 个文件")
            
        except Exception as e:
            logger.error(f"处理失败: {e}", exc_info=True)
    else:
        print("没有可处理的数据流，请检查文件路径")


# ============================================================================
# 主函数
# ============================================================================
if __name__ == "__main__":
    # 运行示例
    example_batch_stream_processing()

