"""Quotation background workers: Phase1/2 and queue dispatch."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.core.task_manager import TaskManager, task_manager
from app.core.database import SessionLocal
from app.core.executor import CancellationToken, executor_manager
from app.core.logging import get_logger
from app.core.quotation_dispatcher import quotation_dispatcher
from app.core.storage import delete_from_minio, download_object_stream
from app.integrations.Quotation_Generation.quotation_pipeline import (
    QuotationPipelineCancelledError,
    QuotationPipelineError,
    run_phase1_keywords_and_pdm,
    run_phase2_u8_bom_inventory,
)
from app.models.orm.file_resource import FileResource
from app.models.orm.quotation_task import QuotationTask, QuotationTaskStatus

logger = get_logger("quotation_generation")

def _mark_task_failed_in_db(task_id: str, error_message: str) -> None:
    db = SessionLocal()
    try:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if not task:
            return
        task.status = QuotationTaskStatus.failed.value
        task.progress = min(task.progress, 99)
        task.error = error_message
        task.message = "任务提交执行器失败"
        task.completed_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(f"标记失败状态异常 {task_id}: {exc}", exc_info=True)
    finally:
        db.close()


def _cleanup_task_files(db: Session, task: QuotationTask) -> Dict[str, Any]:
    cleanup_result = {
        "uploaded_file_deleted": False,
        "temp_image_deleted": False,
        "file_record_deleted": False,
    }

    if task.uploaded_file_minio_path:
        cleanup_result["uploaded_file_deleted"] = delete_from_minio(task.uploaded_file_minio_path)

    if task.temp_image_minio_path:
        cleanup_result["temp_image_deleted"] = delete_from_minio(task.temp_image_minio_path)

    if task.uploaded_file_id:
        file_record = db.query(FileResource).filter(FileResource.id == task.uploaded_file_id).first()
        if file_record:
            # Break FK reference first, otherwise deleting file_resource can rollback the whole tx.
            task.uploaded_file_id = None
            db.flush()
            db.delete(file_record)
            cleanup_result["file_record_deleted"] = True

    return cleanup_result


def safe_cleanup_quotation_task_files(db: Session, task: QuotationTask, task_id: str) -> Dict[str, Any]:
    try:
        return _cleanup_task_files(db, task)
    except Exception as exc:
        logger.error(f"清理报价任务文件失败 {task_id}: {exc}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return {
            "uploaded_file_deleted": False,
            "temp_image_deleted": False,
            "file_record_deleted": False,
            "cleanup_error": str(exc),
        }


def _run_async_task_manager_call(coro: Any) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return
    loop.create_task(coro)


def dispatch_quotation_queue_for_owner(owner_id: str) -> None:
    db = SessionLocal()
    try:
        dispatch_items = quotation_dispatcher.dequeue_for_owner(db, owner_id)
        for item in dispatch_items:
            try:
                future = executor_manager.submit_task(
                    item.task_id,
                    process_quotation_task_background,
                    item.task_id,
                )
                executor_manager.set_task_owner(item.task_id, item.owner_id)
                future.add_done_callback(
                    lambda _, owner_id=item.owner_id: dispatch_quotation_queue_for_owner(owner_id)
                )
            except Exception as exc:
                logger.error(f"提交报价任务到执行器失败 {item.task_id}: {exc}", exc_info=True)
                _mark_task_failed_in_db(item.task_id, f"执行器提交失败: {exc}")
                _run_async_task_manager_call(
                    task_manager.fail_task(item.task_id, str(exc), "任务提交执行器失败")
                )
    except Exception as exc:
        logger.error(f"调度报价任务失败 owner_id={owner_id}: {exc}", exc_info=True)
        db.rollback()
    finally:
        db.close()


# `quotation_tasks.message` is VARCHAR(512); keep a safe headroom when writing.
_MESSAGE_COLUMN_LIMIT = 500


def _clamp_message(message: str, limit: int = _MESSAGE_COLUMN_LIMIT) -> str:
    """Ensure progress messages fit inside quotation_tasks.message (VARCHAR 512)."""
    if message is None:
        return ""
    if len(message) <= limit:
        return message
    suffix = "…(truncated)"
    head = max(0, limit - len(suffix))
    return message[:head] + suffix


def map_parent_inv_code(partid: Any) -> str:
    """PARTID 映射为 U8 ParentInvCode。"""
    if partid is None:
        return ""
    code = str(partid).strip()
    if not code:
        return ""
    if code.startswith("50GB"):
        return f"Z{code[4:]}"
    if code.startswith("50CB"):
        return f"X{code[4:]}"
    if code.startswith("50JC"):
        return f"P{code[4:]}"
    return code


def _convert_pdm_partids_to_u8_codes(partids: List[str]) -> tuple[List[str], List[Dict[str, str]]]:
    """将 PDM PARTID 列表转换为 U8 可查询的 parent_inv_codes。"""
    converted_codes: List[str] = []
    mappings: List[Dict[str, str]] = []
    seen_codes: set[str] = set()

    for partid in partids:
        source = str(partid).strip()
        if not source:
            continue
        mapped = map_parent_inv_code(source)
        if not mapped:
            continue
        mappings.append({"pdm_partid": source, "u8_parent_inv_code": mapped})
        if mapped in seen_codes:
            continue
        seen_codes.add(mapped)
        converted_codes.append(mapped)

    return converted_codes, mappings


def _close_thread_tm(loop: asyncio.AbstractEventLoop, thread_tm: TaskManager) -> None:
    try:
        if hasattr(thread_tm, "storage") and hasattr(thread_tm.storage, "redis_client"):
            if thread_tm.storage.redis_client is not None:
                async def close_redis() -> None:
                    if hasattr(thread_tm.storage.redis_client, "connection_pool"):
                        await thread_tm.storage.redis_client.connection_pool.disconnect()
                    await thread_tm.storage.redis_client.aclose()

                loop.run_until_complete(close_redis())
    except Exception:
        pass
    finally:
        try:
            if not loop.is_closed():
                loop.close()
        except Exception:
            pass


def process_quotation_task_background(token: CancellationToken, task_id: str) -> Dict[str, Any]:
    """Phase 1 worker: OCR -> keywords_payload -> PDM BOM, then pause for approval."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    thread_tm = TaskManager.create_thread_safe_instance()
    db = SessionLocal()

    try:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if not task:
            return {"status": "error", "message": f"任务不存在: {task_id}"}

        loop.run_until_complete(thread_tm.start_task(task_id))

        def update_progress(progress: int, message: str) -> None:
            safe_message = _clamp_message(message)
            task.progress = max(0, min(100, progress))
            task.message = safe_message
            task.status = QuotationTaskStatus.running.value
            db.commit()
            loop.run_until_complete(
                thread_tm.update_task_progress(task_id, task.progress, safe_message)
            )

        if token.is_cancelled():
            raise QuotationPipelineCancelledError("任务在启动前被取消")

        update_progress(5, "正在下载上传PDF")
        with download_object_stream(task.uploaded_file_minio_path) as response:
            pdf_bytes = response.read()

        phase1_result = run_phase1_keywords_and_pdm(
            pdf_bytes=pdf_bytes,
            original_filename=task.uploaded_file_name,
            progress_callback=update_progress,
            cancel_checker=token.is_cancelled,
        )
        task.temp_image_minio_path = phase1_result.temp_image_minio_path

        result_payload = dict(task.result_payload or {})
        result_payload.update(phase1_result.to_dict())

        if not phase1_result.pdm_partids:
            task.status = QuotationTaskStatus.failed.value
            task.progress = min(task.progress, 99)
            task.message = "PDM 查询未返回任何 PARTID"
            task.error = "PDM 结果为空，无法继续 U8 查询"
            task.completed_at = datetime.utcnow()
            task.result_payload = result_payload
            db.commit()
            loop.run_until_complete(thread_tm.fail_task(task_id, task.error, task.message))
            return {"status": "error", "task_id": task_id, "error": task.error}

        converted_u8_codes, pdm_to_u8_mappings = _convert_pdm_partids_to_u8_codes(
            phase1_result.pdm_partids
        )
        result_payload["u8_parent_inv_codes"] = converted_u8_codes
        result_payload["pdm_to_u8_code_mappings"] = pdm_to_u8_mappings
        logger.info(
            "Phase1 PDM->U8 编码转换完成: task_id=%s, pdm_count=%s, u8_count=%s, sample=%s",
            task_id,
            len(phase1_result.pdm_partids),
            len(converted_u8_codes),
            pdm_to_u8_mappings[:8],
        )

        task.status = QuotationTaskStatus.awaiting_approval.value
        task.progress = 50
        task.message = "等待用户审核 PDM 结果"
        task.result_payload = result_payload
        task.error = None
        db.commit()

        loop.run_until_complete(
            thread_tm.update_task_progress(task_id, task.progress, task.message)
        )
        return {"status": "awaiting_approval", "task_id": task_id}

    except QuotationPipelineCancelledError as exc:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if task:
            cleanup_result = safe_cleanup_quotation_task_files(db, task, task_id)
            existing_payload = dict(task.result_payload or {})
            existing_payload["cleanup"] = cleanup_result
            task.status = QuotationTaskStatus.cancelled.value
            task.message = "任务已取消"
            task.error = str(exc)
            task.completed_at = datetime.utcnow()
            task.result_payload = existing_payload
            db.commit()
        loop.run_until_complete(thread_tm.fail_task(task_id, str(exc), "任务已取消"))
        return {"status": "cancelled", "task_id": task_id}

    except Exception as exc:
        logger.error(f"报价任务 Phase1 执行失败 {task_id}: {exc}", exc_info=True)
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if task:
            cleanup_result = safe_cleanup_quotation_task_files(db, task, task_id)
            existing_payload = dict(task.result_payload or {})
            existing_payload["cleanup"] = cleanup_result
            task.status = QuotationTaskStatus.failed.value
            task.message = "Phase1 执行失败"
            task.error = str(exc)
            task.completed_at = datetime.utcnow()
            task.result_payload = existing_payload
            db.commit()
        loop.run_until_complete(thread_tm.fail_task(task_id, str(exc), "Phase1 执行失败"))
        return {"status": "error", "task_id": task_id, "error": str(exc)}

    finally:
        try:
            db.close()
        except Exception:
            pass
        _close_thread_tm(loop, thread_tm)


def process_quotation_task_phase2_background(
    token: CancellationToken, task_id: str
) -> Dict[str, Any]:
    """Phase 2 worker: call U8 BOM Inventory using previously-collected PARTIDs."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    thread_tm = TaskManager.create_thread_safe_instance()
    db = SessionLocal()

    try:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if not task:
            return {"status": "error", "message": f"任务不存在: {task_id}"}

        loop.run_until_complete(thread_tm.start_task(task_id))

        def update_progress(progress: int, message: str) -> None:
            safe_message = _clamp_message(message)
            task.progress = max(0, min(100, progress))
            task.message = safe_message
            task.status = QuotationTaskStatus.running.value
            db.commit()
            loop.run_until_complete(
                thread_tm.update_task_progress(task_id, task.progress, safe_message)
            )

        if token.is_cancelled():
            raise QuotationPipelineCancelledError("任务在启动前被取消")

        existing_payload = dict(task.result_payload or {})
        approved_partids = existing_payload.get("approved_partids")
        if isinstance(approved_partids, list) and approved_partids:
            selected_partids = [str(partid) for partid in approved_partids if str(partid).strip()]
            source = "approved_partids"
        else:
            fallback = existing_payload.get("pdm_partids") or []
            selected_partids = [str(partid) for partid in fallback if str(partid).strip()]
            source = "pdm_partids(fallback)"

        logger.info(
            "Phase2 准备执行 U8 查询: task_id=%s, source=%s, selected_count=%s, sample=%s",
            task_id,
            source,
            len(selected_partids),
            selected_partids[:8],
        )

        if not selected_partids:
            logger.warning(
                "Phase2 缺少可用 PARTID: task_id=%s, payload_keys=%s",
                task_id,
                list(existing_payload.keys()),
            )
            raise QuotationPipelineError("任务缺少已批准的 PARTID 列表，无法继续 U8 查询")

        update_progress(60, f"开始 U8 BOM Inventory 查询（{len(selected_partids)} 项）")

        phase2_result = run_phase2_u8_bom_inventory(
            pdm_partids=selected_partids,
            keywords_payload=existing_payload.get("keywords_payload"),
            progress_callback=update_progress,
            cancel_checker=token.is_cancelled,
        )

        safe_cleanup_quotation_task_files(db, task, task_id)

        u8_total = None
        u8_items = None
        if isinstance(phase2_result.u8_result, dict):
            u8_total = phase2_result.u8_result.get("total")
            u8_items = phase2_result.u8_result.get("items")
        logger.info(
            "Phase2 U8 查询结果: task_id=%s, total=%s, items_len=%s",
            task_id,
            u8_total,
            len(u8_items) if isinstance(u8_items, list) else None,
        )

        final_payload: Dict[str, Any] = {
            "keywords_payload": existing_payload.get("keywords_payload"),
            "approved_partids": selected_partids,
            "u8_result": phase2_result.u8_result,
            "u8_result_by_type": phase2_result.u8_result_by_type,
            "u8_result_type_summary": phase2_result.u8_result_type_summary,
        }

        task.status = QuotationTaskStatus.completed.value
        task.progress = 100
        task.message = "任务完成（U8 BOM Inventory 已返回）"
        task.result_payload = final_payload
        task.error = None
        task.completed_at = datetime.utcnow()
        db.commit()

        loop.run_until_complete(thread_tm.complete_task(task_id, final_payload, task.message))
        return {"status": "success", "task_id": task_id}

    except QuotationPipelineCancelledError as exc:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if task:
            cleanup_result = safe_cleanup_quotation_task_files(db, task, task_id)
            existing_payload = dict(task.result_payload or {})
            existing_payload["cleanup"] = cleanup_result
            task.status = QuotationTaskStatus.cancelled.value
            task.message = "任务已取消"
            task.error = str(exc)
            task.completed_at = datetime.utcnow()
            task.result_payload = existing_payload
            db.commit()
        loop.run_until_complete(thread_tm.fail_task(task_id, str(exc), "任务已取消"))
        return {"status": "cancelled", "task_id": task_id}

    except Exception as exc:
        logger.error(f"报价任务 Phase2 执行失败 {task_id}: {exc}", exc_info=True)
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if task:
            # Preserve PDM results for debugging; do not clear result_payload.
            existing_payload = dict(task.result_payload or {})
            task.status = QuotationTaskStatus.failed.value
            task.message = "Phase2 执行失败"
            task.error = str(exc)
            task.completed_at = datetime.utcnow()
            task.result_payload = existing_payload
            db.commit()
        loop.run_until_complete(thread_tm.fail_task(task_id, str(exc), "Phase2 执行失败"))
        return {"status": "error", "task_id": task_id, "error": str(exc)}

    finally:
        try:
            db.close()
        except Exception:
            pass
        _close_thread_tm(loop, thread_tm)


def dispatch_quotation_phase2(task_id: str, owner_id: str) -> None:
    """Submit the Phase 2 worker. Must be called after the DB status flip.

    The executor retains Phase 1's Future under the same task_id for history,
    so we evict it first to allow resubmitting with the same business id.
    """
    try:
        executor_manager.forget_task(task_id)
        future = executor_manager.submit_task(
            task_id,
            process_quotation_task_phase2_background,
            task_id,
        )
        executor_manager.set_task_owner(task_id, owner_id)
        future.add_done_callback(lambda _, oid=owner_id: dispatch_quotation_queue_for_owner(oid))
    except Exception as exc:
        logger.error(f"Phase2 提交执行器失败 {task_id}: {exc}", exc_info=True)
        _mark_task_failed_in_db(task_id, f"执行器提交失败: {exc}")
        _run_async_task_manager_call(
            task_manager.fail_task(task_id, str(exc), "Phase2 提交执行器失败")
        )

