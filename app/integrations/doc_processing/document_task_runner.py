"""Thread-pool document processing worker (MinIO + pipeline)."""

from __future__ import annotations

import asyncio
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.executor import CancellationToken
from app.core.time_utils import utcnow_naive
from app.core.logging import get_logger
from app.core.async_storage import (
    async_delete_from_minio,
    async_stat_object,
    async_upload_stream_to_minio,
)
from app.models.orm.file_resource import FileResource

logger = get_logger("document_processing")


async def upload_and_register_documents(
    db: AsyncSession, files, normalized_uploader: str
) -> List[int]:
    """
    Stream uploads to MinIO under documents/ and persist FileResource rows.
    files: iterable of Starlette UploadFile-like (filename, file, content_type, size).
    """
    file_ids: List[int] = []
    for file in files:
        if not getattr(file, "filename", None):
            logger.warning("跳过没有文件名的文件")
            continue
        minio_path: Optional[str] = None
        try:
            suffix = Path(file.filename).suffix
            unique_id = uuid.uuid4().hex
            timestamp = utcnow_naive().strftime("%Y%m%d_%H%M%S")
            unique_name = f"{timestamp}_{unique_id}{suffix}"
            minio_path = f"documents/{unique_name}"
            file_size = getattr(file, "size", None) or -1
            content_type = file.content_type or "application/octet-stream"
            await async_upload_stream_to_minio(file.file, minio_path, file_size, content_type)
            if file_size == -1:
                try:
                    stat = await async_stat_object(minio_path)
                    file_size = stat.size
                except Exception:
                    file_size = 0
            file_record = FileResource(
                file_name=file.filename,
                unique_name=unique_name,
                minio_object_path=minio_path,
                content_type=content_type,
                file_size=file_size,
                uploader=normalized_uploader,
            )
            db.add(file_record)
            await db.commit()
            await db.refresh(file_record)
            file_ids.append(file_record.id)
            logger.info("文件上传成功: %s (ID: %s)", file.filename, file_record.id)
        except Exception as e:
            logger.error("上传文件失败 %s: %s", getattr(file, "filename", ""), e, exc_info=True)
            await db.rollback()
            # Compensating delete: if the MinIO upload succeeded but the DB commit
            # failed, reclaim the object so it does not orphan. minio_path is only
            # defined after the upload assignment above.
            try:
                await async_delete_from_minio(minio_path)
                logger.warning("DB 落库失败后回删 MinIO 对象: %s", minio_path)
            except Exception as cleanup_err:
                logger.error("回删 MinIO 对象失败 path=%s err=%s", minio_path, cleanup_err)
    return file_ids


def process_documents_background(
    token: CancellationToken,
    task_id: str,
    file_ids: List[int],
    instance_id: int,
    chunk_size: int,
    chunk_overlap: int,
):
    """Run in thread pool: token from ExecutorManager; do not await here."""
    from app.core.task_manager import TaskManager
    from app.integrations.doc_processing.pipeline import DocumentProcessingPipeline

    logger.info("[%s] 开始后台处理，文件数: %s", task_id, len(file_ids))

    thread_tm = TaskManager.create_thread_safe_instance()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        if token.is_cancelled():
            logger.info("[%s] 任务在启动前被取消", task_id)
            try:
                loop.run_until_complete(
                    thread_tm.fail_task(task_id, "用户取消任务", "任务在启动前被取消")
                )
            except Exception as e:
                logger.warning("[%s] 回写取消状态失败: %s", task_id, e)
            return {"status": "cancelled", "message": "任务在启动前被取消"}

        task_exists = False
        for attempt in range(5):
            try:
                task_status = loop.run_until_complete(thread_tm.get_task_status(task_id))
                if task_status:
                    task_exists = True
                    logger.info("[%s] 任务已找到，开始处理", task_id)
                    break
            except Exception as e:
                logger.warning(
                    "[%s] 查询任务状态失败 (尝试 %s/5): %s", task_id, attempt + 1, e
                )
            time.sleep(0.3)

        if not task_exists:
            logger.error("[%s] 任务创建超时，无法启动", task_id)
            try:
                loop.run_until_complete(
                    thread_tm.fail_task(
                        task_id, "任务记录同步超时，无法启动", "任务创建超时"
                    )
                )
            except Exception as e:
                logger.warning("[%s] 回写超时失败状态失败: %s", task_id, e)
            return {"status": "error", "message": "任务创建超时"}

        loop.run_until_complete(thread_tm.start_task(task_id))

        db_config = {
            "host": settings.POSTGRES_SERVER,
            "user": settings.POSTGRES_USER,
            "password": settings.POSTGRES_PASSWORD,
            "database": settings.POSTGRES_DB,
            "port": settings.POSTGRES_PORT,
        }
        pipeline = DocumentProcessingPipeline(
            db_config=db_config,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        logger.info(
            "[%s] 正在从 MinIO 下载并逐文件处理 %s 个文件...", task_id, len(file_ids)
        )
        downloaded_count = 0
        total_processed = 0
        n_files = len(file_ids)
        db = SessionLocal()
        try:
            for i, file_id in enumerate(file_ids):
                if token.is_cancelled():
                    logger.info("[%s] 任务被取消，停止下载", task_id)
                    loop.run_until_complete(
                        thread_tm.fail_task(task_id, "用户取消任务", "任务已取消")
                    )
                    return {"status": "cancelled", "message": "任务被取消"}

                file_record = (
                    db.query(FileResource).filter(FileResource.id == file_id).first()
                )
                if not file_record:
                    logger.warning("[%s] 文件 ID %s 不存在，跳过", task_id, file_id)
                    continue

                progress = int((i / max(n_files, 1)) * 30)
                loop.run_until_complete(
                    thread_tm.update_task_progress(
                        task_id,
                        progress,
                        f"正在下载第 {i+1}/{n_files} 个文件: {file_record.file_name}",
                    )
                )
                try:
                    from app.core.storage import save_file_from_minio

                    temp_path = save_file_from_minio(file_record.minio_object_path)
                    stream = BytesIO(temp_path.read_bytes())
                    stream.name = file_record.file_name
                    temp_path.unlink(missing_ok=True)
                    downloaded_count += 1
                except Exception as e:
                    logger.error(
                        "[%s] 下载文件失败 %s: %s", task_id, file_record.file_name, e
                    )
                    continue

                if token.is_cancelled():
                    loop.run_until_complete(
                        thread_tm.fail_task(task_id, "用户取消任务", "任务已取消")
                    )
                    return {"status": "cancelled", "message": "任务被取消"}

                mid = 30 + int((i + 1) / max(n_files, 1) * 55)
                loop.run_until_complete(
                    thread_tm.update_task_progress(
                        task_id,
                        min(mid, 85),
                        f"处理文件 {i+1}/{n_files}: {file_record.file_name}",
                    )
                )
                try:
                    one_result = pipeline.process(
                        input_data=[stream],
                        instance_id=instance_id,
                    )
                    total_processed += int(one_result.get("processed_files", 0) or 0)
                except Exception as e:
                    logger.error(
                        "[%s] 处理文件失败 %s: %s",
                        task_id,
                        file_record.file_name,
                        e,
                        exc_info=True,
                    )
                    raise
                finally:
                    stream.close()
                    del stream

            if not downloaded_count:
                raise ValueError("没有成功下载任何文件")

            if token.is_cancelled():
                logger.info("[%s] 任务被取消，停止处理", task_id)
                loop.run_until_complete(
                    thread_tm.fail_task(task_id, "用户取消任务", "任务已取消")
                )
                return {"status": "cancelled", "message": "任务被取消"}

            logger.info(
                "[%s] 已处理 %s 个文件，向量化成功段数: %s",
                task_id,
                downloaded_count,
                total_processed,
            )
            loop.run_until_complete(
                thread_tm.update_task_progress(task_id, 90, "正在保存结果...")
            )
            result = {
                "status": "success",
                "processed_files": total_processed,
                "total_files": downloaded_count,
            }
            final_result = {
                "processed_files": total_processed,
                "total_files": len(file_ids),
                "status": result.get("status"),
                "instance_id": instance_id,
            }
            loop.run_until_complete(
                thread_tm.complete_task(task_id, final_result, "文档处理完成")
            )
            logger.info("[%s] 处理完成: %s", task_id, final_result)
            return final_result
        finally:
            try:
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()
    except Exception as e:
        logger.error("[%s] 处理失败: %s", task_id, e, exc_info=True)
        try:
            loop.run_until_complete(
                thread_tm.fail_task(task_id, str(e), "文档处理失败")
            )
        except Exception as e2:
            logger.error("[%s] 标记失败状态时出错: %s", task_id, e2)
        return {"status": "error", "message": str(e)}
    finally:
        try:
            if hasattr(thread_tm, "storage") and hasattr(thread_tm.storage, "redis_client"):
                if thread_tm.storage.redis_client is not None:
                    try:
                        async def close_redis_with_timeout():
                            if hasattr(
                                thread_tm.storage.redis_client, "connection_pool"
                            ):
                                await (
                                    thread_tm.storage.redis_client.connection_pool.disconnect()
                                )
                            await thread_tm.storage.redis_client.aclose()

                        loop.run_until_complete(
                            asyncio.wait_for(close_redis_with_timeout(), timeout=2.0)
                        )
                        logger.debug("[%s] Redis连接已关闭", task_id)
                    except asyncio.TimeoutError:
                        logger.warning("[%s] Redis关闭超时，强制继续", task_id)
                    except Exception as e:
                        logger.warning("[%s] 关闭Redis连接失败: %s", task_id, e)
            if loop and not loop.is_closed():
                loop.close()
                logger.debug("[%s] 事件循环已关闭", task_id)
        except Exception as e:
            logger.warning("[%s] 清理资源时出错: %s", task_id, e)
