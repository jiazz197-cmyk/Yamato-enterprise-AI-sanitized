"""Quotation background workers: Phase1/2 and queue dispatch."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.task_manager import TaskManager, task_manager
from app.core.database import SessionLocal
from app.core.executor import CancellationToken, executor_manager
from app.core.logging import get_logger
from app.core.quotation_dispatcher import quotation_dispatcher
from app.core.storage import delete_from_minio, download_object_stream
from app.adapters.quotation.deps import (
    build_execute_quotation_phase1_use_case,
    build_execute_quotation_phase2_use_case,
)
from app.domain.quotation.exceptions import QuotationPipelineCancelledError, QuotationPipelineError
from app.domain.quotation.partid_mapping import convert_partids_to_u8_codes
from app.usecases.quotation.execute_phase1 import ExecuteQuotationPhase1Command
from app.usecases.quotation.execute_phase2 import ExecuteQuotationPhase2Command
from app.models.orm.file_resource import FileResource
from app.models.orm.quotation_task import QuotationTask, QuotationTaskStatus

logger = get_logger("quotation_generation")

_XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _upload_u8_result_by_type_xlsx_to_minio(
    *,
    task_id: str,
    uploaded_file_name: str,
    u8_result_by_type: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str]]:
    """Build multi-sheet xlsx from ``u8_result_by_type`` and upload via ``MinioFileStorageAdapter``.

    Returns ``(minio_object_path, download_filename)`` or ``(None, None)`` if skipped or upload fails.
    """
    # Lazy imports: ``persistence`` imports this module at load time.
    from app.adapters.quotation.persistence import MinioFileStorageAdapter
    from app.adapters.quotation.u8_result_by_type_csv import U8ResultByTypeCsvAdapter
    from app.core.exceptions import APIException

    try:
        xlsx_export = U8ResultByTypeCsvAdapter().export_xlsx_workbook(u8_result_by_type)
    except ImportError as exc:
        logger.warning("Phase2 skip u8_by_type xlsx: openpyxl missing (%s)", exc)
        return None, None

    object_path = f"quotation-results/{task_id}/u8_by_type.xlsx"
    stem = Path(uploaded_file_name or "").stem or "quotation"
    safe_stem = re.sub(r"[^\w\u4e00-\u9fff\-.]+", "_", stem).strip("_") or "quotation"
    download_name = f"{safe_stem}_u8_by_type.xlsx"

    try:
        MinioFileStorageAdapter().upload_pdf(
            object_path=object_path,
            file_bytes=xlsx_export.content,
            content_type=_XLSX_CONTENT_TYPE,
        )
    except APIException as exc:
        logger.warning("Phase2 u8_by_type xlsx MinIO upload failed task_id=%s: %s", task_id, exc)
        return None, None
    except Exception as exc:
        logger.warning(
            "Phase2 u8_by_type xlsx upload error task_id=%s: %s",
            task_id,
            exc,
            exc_info=True,
        )
        return None, None

    return object_path, download_name


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


def _cleanup_task_files_by_id(task_id: str) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if not task:
            return {}
        cleanup_result = safe_cleanup_quotation_task_files(db, task, task_id)
        db.commit()
        return cleanup_result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


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


# Keep progress messages compact; detailed query parameters belong in logs, not task cards.
_MESSAGE_COLUMN_LIMIT = 220


def _clamp_message(message: str, limit: int = _MESSAGE_COLUMN_LIMIT) -> str:
    """Ensure progress messages fit inside quotation_tasks.message (VARCHAR 512)."""
    if message is None:
        return ""
    if len(message) <= limit:
        return message
    suffix = "…(truncated)"
    head = max(0, limit - len(suffix))
    return message[:head] + suffix


def _query_result_summary(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {"total": 0, "items_count": 0}
    items = value.get("items")
    return {
        "total": value.get("total"),
        "items_count": len(items) if isinstance(items, list) else 0,
    }


def _u8_by_type_summary(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {"total": 0, "items": []}
    groups = value.get("items")
    compact_groups = []
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            compact_groups.append(
                {
                    "type": group.get("type"),
                    "u8_parent_inv_codes": group.get("u8_parent_inv_codes"),
                    "total": group.get("total"),
                    "items_count": len(group.get("items")) if isinstance(group.get("items"), list) else 0,
                }
            )
    return {
        "total": value.get("total"),
        "items_count": len(groups) if isinstance(groups, list) else 0,
        "items": compact_groups,
    }


def _patch_task_fields(task_id: str, updates: Dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if not task:
            return
        for key, value in updates.items():
            setattr(task, key, value)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


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
    existing_payload: Dict[str, Any] = {}
    uploaded_file_minio_path = ""
    uploaded_file_name = ""

    try:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if not task:
            return {"status": "error", "message": f"任务不存在: {task_id}"}
        existing_payload = dict(task.result_payload or {})
        uploaded_file_minio_path = task.uploaded_file_minio_path
        uploaded_file_name = task.uploaded_file_name
        db.close()

        loop.run_until_complete(thread_tm.start_task(task_id))

        def update_progress(progress: int, message: str) -> None:
            safe_message = _clamp_message(message)
            safe_progress = max(0, min(100, progress))
            _patch_task_fields(
                task_id,
                {
                    "progress": safe_progress,
                    "message": safe_message,
                    "status": QuotationTaskStatus.running.value,
                },
            )
            loop.run_until_complete(
                thread_tm.update_task_progress(task_id, safe_progress, safe_message)
            )

        if token.is_cancelled():
            raise QuotationPipelineCancelledError("任务在启动前被取消")

        update_progress(5, "正在下载上传PDF")
        with download_object_stream(uploaded_file_minio_path) as response:
            pdf_bytes = response.read()

        phase1_uc = build_execute_quotation_phase1_use_case()
        phase1_result = phase1_uc.execute(
            ExecuteQuotationPhase1Command(
                pdf_bytes=pdf_bytes,
                original_filename=uploaded_file_name,
                progress_callback=update_progress,
                cancel_checker=token.is_cancelled,
            )
        )

        result_payload = dict(existing_payload)
        result_payload.update(phase1_result.to_dict())

        if not phase1_result.pdm_partids:
            error_message = "PDM 结果为空，无法继续 U8 查询"
            _patch_task_fields(
                task_id,
                {
                    "status": QuotationTaskStatus.failed.value,
                    "progress": 99,
                    "message": "PDM 查询未返回任何 PARTID",
                    "error": error_message,
                    "completed_at": datetime.utcnow(),
                    "temp_image_minio_path": phase1_result.temp_image_minio_path,
                    "result_payload": result_payload,
                },
            )
            loop.run_until_complete(thread_tm.fail_task(task_id, error_message, "PDM 查询未返回任何 PARTID"))
            return {"status": "error", "task_id": task_id, "error": error_message}

        converted_u8_codes, pdm_to_u8_mappings = convert_partids_to_u8_codes(
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

        _patch_task_fields(
            task_id,
            {
                "status": QuotationTaskStatus.awaiting_approval.value,
                "progress": 50,
                "message": "等待用户审核 PDM 结果",
                "temp_image_minio_path": phase1_result.temp_image_minio_path,
                "result_payload": result_payload,
                "error": None,
            },
        )

        loop.run_until_complete(
            thread_tm.update_task_progress(task_id, 50, "等待用户审核 PDM 结果")
        )
        return {"status": "awaiting_approval", "task_id": task_id}

    except QuotationPipelineCancelledError as exc:
        cleanup_result = _cleanup_task_files_by_id(task_id)
        existing_payload["cleanup"] = cleanup_result
        _patch_task_fields(
            task_id,
            {
                "status": QuotationTaskStatus.cancelled.value,
                "message": "任务已取消",
                "error": str(exc),
                "completed_at": datetime.utcnow(),
                "result_payload": existing_payload,
            },
        )
        loop.run_until_complete(thread_tm.fail_task(task_id, str(exc), "任务已取消"))
        return {"status": "cancelled", "task_id": task_id}

    except Exception as exc:
        logger.error(f"报价任务 Phase1 执行失败 {task_id}: {exc}", exc_info=True)
        cleanup_result = _cleanup_task_files_by_id(task_id)
        existing_payload["cleanup"] = cleanup_result
        _patch_task_fields(
            task_id,
            {
                "status": QuotationTaskStatus.failed.value,
                "message": "Phase1 执行失败",
                "error": str(exc),
                "completed_at": datetime.utcnow(),
                "result_payload": existing_payload,
            },
        )
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
    existing_payload: Dict[str, Any] = {}
    uploaded_file_name = ""

    try:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if not task:
            return {"status": "error", "message": f"任务不存在: {task_id}"}
        existing_payload = dict(task.result_payload or {})
        uploaded_file_name = task.uploaded_file_name
        db.close()

        loop.run_until_complete(thread_tm.start_task(task_id))

        def update_progress(progress: int, message: str) -> None:
            safe_message = _clamp_message(message)
            safe_progress = max(0, min(100, progress))
            _patch_task_fields(
                task_id,
                {
                    "progress": safe_progress,
                    "message": safe_message,
                    "status": QuotationTaskStatus.running.value,
                },
            )
            loop.run_until_complete(
                thread_tm.update_task_progress(task_id, safe_progress, safe_message)
            )

        if token.is_cancelled():
            raise QuotationPipelineCancelledError("任务在启动前被取消")

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

        phase2_uc = build_execute_quotation_phase2_use_case()
        phase2_result = phase2_uc.execute(
            ExecuteQuotationPhase2Command(
                pdm_partids=selected_partids,
                keywords_payload=existing_payload.get("keywords_payload"),
                pdm_result=existing_payload.get("pdm_result"),
                approved_partids=selected_partids,
                progress_callback=update_progress,
                cancel_checker=token.is_cancelled,
            )
        )

        cleanup_result = _cleanup_task_files_by_id(task_id)

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

        full_u8_by_type = (
            phase2_result.u8_result_by_type
            if isinstance(phase2_result.u8_result_by_type, dict)
            else {}
        )
        final_payload: Dict[str, Any] = {
            "keywords_payload": existing_payload.get("keywords_payload"),
            "approved_partids": selected_partids,
            "u8_result": _query_result_summary(phase2_result.u8_result),
            "u8_result_by_type": _u8_by_type_summary(full_u8_by_type),
            "u8_result_type_summary": phase2_result.u8_result_type_summary,
            "cleanup": cleanup_result,
        }

        xlsx_path, xlsx_name = _upload_u8_result_by_type_xlsx_to_minio(
            task_id=task_id,
            uploaded_file_name=uploaded_file_name,
            u8_result_by_type=full_u8_by_type,
        )
        if xlsx_path and xlsx_name:
            final_payload["u8_result_by_type_xlsx_minio_path"] = xlsx_path
            final_payload["u8_result_by_type_xlsx_filename"] = xlsx_name

        completed_message = "任务完成（U8 BOM Inventory 已返回）"
        _patch_task_fields(
            task_id,
            {
                "status": QuotationTaskStatus.completed.value,
                "progress": 100,
                "message": completed_message,
                "result_payload": final_payload,
                "error": None,
                "completed_at": datetime.utcnow(),
            },
        )

        loop.run_until_complete(thread_tm.complete_task(task_id, final_payload, completed_message))
        return {"status": "success", "task_id": task_id}

    except QuotationPipelineCancelledError as exc:
        cleanup_result = _cleanup_task_files_by_id(task_id)
        existing_payload["cleanup"] = cleanup_result
        _patch_task_fields(
            task_id,
            {
                "status": QuotationTaskStatus.cancelled.value,
                "message": "任务已取消",
                "error": str(exc),
                "completed_at": datetime.utcnow(),
                "result_payload": existing_payload,
            },
        )
        loop.run_until_complete(thread_tm.fail_task(task_id, str(exc), "任务已取消"))
        return {"status": "cancelled", "task_id": task_id}

    except Exception as exc:
        logger.error(f"报价任务 Phase2 执行失败 {task_id}: {exc}", exc_info=True)
        _patch_task_fields(
            task_id,
            {
                "status": QuotationTaskStatus.failed.value,
                "message": "Phase2 执行失败",
                "error": str(exc),
                "completed_at": datetime.utcnow(),
                "result_payload": existing_payload,
            },
        )
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

