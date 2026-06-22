"""U8 BOM + Inventory recursive walk.

`InvCode` / PartId style codes are passed as pymssql parameters (`%s` placeholders);
parent codes are normalized from trusted API input, not ad-hoc SQL.
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.core.config import settings
from app.core.logging import get_logger

from app.integrations.sqlserver.client import (
    PymssqlConnectionPool,
    get_sql_client_pool,
    pooled_client,
)
from app.integrations.sqlserver.exceptions import QueryCancelledError, raise_if_cancelled

logger = get_logger("database.sqlserver")

_DEADLOCK_RETRY_DELAYS_SEC: tuple[float, ...] = (0.3, 0.8, 1.5)


# ---------------------------------------------------------------------------
# 诊断计数器：追踪并行展开的实际并发度和 SQL vs Python 时间比。
# 仅用于日志诊断，不影响功能。
# ---------------------------------------------------------------------------
_diag_active_threads: int = 0
_diag_max_concurrent: int = 0
_diag_sql_time_sec: float = 0.0
_diag_python_time_sec: float = 0.0
_diag_query_count: int = 0
_diag_lock = threading.Lock()


def _diag_thread_enter() -> None:
    global _diag_active_threads, _diag_max_concurrent
    with _diag_lock:
        _diag_active_threads += 1
        if _diag_active_threads > _diag_max_concurrent:
            _diag_max_concurrent = _diag_active_threads


def _diag_thread_exit() -> None:
    global _diag_active_threads
    with _diag_lock:
        _diag_active_threads -= 1


def _diag_record_sql(elapsed: float) -> None:
    global _diag_sql_time_sec, _diag_query_count
    with _diag_lock:
        _diag_sql_time_sec += elapsed
        _diag_query_count += 1


def _diag_record_python(elapsed: float) -> None:
    global _diag_python_time_sec
    with _diag_lock:
        _diag_python_time_sec += elapsed


def _diag_reset() -> None:
    global _diag_active_threads, _diag_max_concurrent, _diag_sql_time_sec, _diag_python_time_sec, _diag_query_count
    with _diag_lock:
        _diag_active_threads = 0
        _diag_max_concurrent = 0
        _diag_sql_time_sec = 0.0
        _diag_python_time_sec = 0.0
        _diag_query_count = 0


def _diag_log_summary(label: str) -> None:
    with _diag_lock:
        sql_t = _diag_sql_time_sec
        py_t = _diag_python_time_sec
        qc = _diag_query_count
        mc = _diag_max_concurrent
    if qc > 0:
        logger.info(
            "[DIAG] %s: max_concurrent_threads=%s, query_count=%s, "
            "sql_time=%.2fs, python_time=%.2fs, avg_sql=%.1fms, "
            "sql_pct=%.0f%%",
            label, mc, qc, sql_t, py_t,
            (sql_t / qc) * 1000,
            (sql_t / (sql_t + py_t) * 100) if (sql_t + py_t) > 0 else 0,
        )


class SharedChildrenCache:
    """Thread-safe cross-root cache for BOM children lookups.

    Multiple worker threads (each with its own pooled connection) consult this
    shared cache so that a subassembly appearing under several root codes is
    fetched from SQL Server only once globally.

    The SQL fetch runs OUTSIDE the lock: a short critical section registers a
    per-key ``threading.Event`` in-flight marker (or returns the cached result
    if already present). Same-code waiters block on the Event while the first
    fetcher runs the query on its own connection; different-code requests
    proceed in parallel without contending. This preserves cross-root dedup
    without serializing distinct queries through a single lock.

    On a fetch failure the exception is cached against the key so woken waiters
    re-raise it directly instead of each independently re-querying (which would
    amplify DB load under persistent failures via deadlock-retry backoff). A
    short negative-TTL (``_NEG_TTL_SEC``) bounds how long a cached failure is
    reused, allowing a later retry after the condition clears.

    Rows are shared read-only after population, so returning the same list
    object to multiple walkers is safe as long as walkers do not mutate it
    (they only read).
    """

    _NEG_TTL_SEC: float = 5.0

    def __init__(self) -> None:
        self._store: Dict[str, List[Dict[str, Any]]] = {}
        self._inflight: Dict[str, threading.Event] = {}
        # key -> (exception, expiry_timestamp)
        self._errors: Dict[str, tuple[BaseException, float]] = {}
        self._lock = threading.Lock()

    def get_or_fetch(
        self,
        parent_inv_code: str,
        fetch_fn: Callable[[], List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        # Fast path: already cached.
        cached = self._store.get(parent_inv_code)
        if cached is not None:
            return cached

        # Short critical section: register an in-flight marker or join an
        # existing one. Does NOT run fetch_fn() under the lock.
        with self._lock:
            cached = self._store.get(parent_inv_code)
            if cached is not None:
                return cached

            # Expire a stale cached failure so a later caller may retry.
            err_entry = self._errors.get(parent_inv_code)
            if err_entry is not None and time.time() >= err_entry[1]:
                self._errors.pop(parent_inv_code, None)
                err_entry = None

            event = self._inflight.get(parent_inv_code)
            if event is None:
                # We are the first fetcher for this code.
                event = threading.Event()
                self._inflight[parent_inv_code] = event
                is_fetcher = True
            else:
                is_fetcher = False

        if is_fetcher:
            # Run the SQL query OUTSIDE the lock on this thread's connection.
            try:
                rows = fetch_fn()
                with self._lock:
                    self._store[parent_inv_code] = rows
                    self._inflight.pop(parent_inv_code, None)
                    self._errors.pop(parent_inv_code, None)
                event.set()
                return rows
            except BaseException as exc:
                # Cache the failure so waiters re-raise instead of re-querying.
                with self._lock:
                    self._errors[parent_inv_code] = (exc, time.time() + self._NEG_TTL_SEC)
                    self._inflight.pop(parent_inv_code, None)
                event.set()
                raise
        else:
            # Wait for the in-flight fetcher to finish, then read the result.
            event.wait()
            cached = self._store.get(parent_inv_code)
            if cached is not None:
                return cached
            # Fetcher failed: re-raise the cached exception (no re-query).
            with self._lock:
                err_entry = self._errors.get(parent_inv_code)
            if err_entry is not None:
                raise err_entry[0]
            # No cached error and no result (shouldn't happen) — fail loudly.
            raise RuntimeError(
                f"SharedChildrenCache: in-flight fetch for {parent_inv_code!r} "
                f"completed without result or cached error"
            )


# ---------------------------------------------------------------------------
# BOM 任务并发信号量：限制同时运行的 BOM 查询任务数。
#
# 每个 BOM 任务会建立最多 U8_BOM_PARALLEL_WORKERS 条 U8 SQL Server 连接，
# 信号量大小 = U8_BOM_MAX_CONCURRENT_TASKS，二者乘积即最坏情况下到 U8 库的
# 并发连接数（受 config.U8_BOM_MAX_TOTAL_CONNECTIONS 校验约束）。
#
# 与全局线程池 EXECUTOR_MAX_WORKERS 解耦：后者管 OCR/导入等非 BOM 任务，
# 不受本信号量约束，因此调大 EXECUTOR 不会增加 U8 连接压力。
# ---------------------------------------------------------------------------
_bom_concurrency_semaphore: Optional[threading.BoundedSemaphore] = None
_bom_semaphore_init_lock = threading.Lock()


def _get_bom_concurrency_semaphore() -> threading.BoundedSemaphore:
    """Lazily build (once) the BOM task concurrency semaphore from settings."""
    global _bom_concurrency_semaphore
    if _bom_concurrency_semaphore is None:
        with _bom_semaphore_init_lock:
            if _bom_concurrency_semaphore is None:
                size = settings.U8_BOM_MAX_CONCURRENT_TASKS
                _bom_concurrency_semaphore = threading.BoundedSemaphore(size)
                logger.info(
                    "U8 BOM 并发信号量初始化: max_concurrent_tasks=%s "
                    "(单任务并行=%s, 最坏连接数=%s)",
                    size,
                    settings.U8_BOM_PARALLEL_WORKERS,
                    size * settings.U8_BOM_PARALLEL_WORKERS,
                )
    return _bom_concurrency_semaphore


def _acquire_bom_slot(
    cancel_checker: Optional[Callable[[], bool]] = None,
) -> None:
    """Block until a BOM concurrency slot is available (supports cancellation).

    Polls with a 1s timeout so a cancel request can still interrupt the wait;
    re-checks ``cancel_checker`` between attempts.
    """
    sem = _get_bom_concurrency_semaphore()
    waited = False
    while not sem.acquire(timeout=1.0):
        if not waited:
            logger.info("U8 BOM 并发槽位已满，任务排队等待...")
            waited = True
        raise_if_cancelled(cancel_checker)
    if waited:
        logger.info("U8 BOM 并发槽位已获取，开始执行查询")


def _release_bom_slot() -> None:
    sem = _get_bom_concurrency_semaphore()
    try:
        sem.release()
    except ValueError:
        # 信号量计数已满（重复释放），忽略以保持健壮
        pass


def _is_sqlserver_deadlock_error(exc: BaseException) -> bool:
    for arg in getattr(exc, "args", ()):  # pymssql usually exposes 1205 in args[0]
        if arg == 1205:
            return True
        if isinstance(arg, bytes) and b"1205" in arg:
            return True
        if isinstance(arg, str) and "1205" in arg:
            return True
    text = str(exc)
    return "1205" in text and "deadlock" in text.lower()


def _query_with_deadlock_retry(
    client: Any,
    sql: str,
    *,
    log_label: str,
    cancel_checker: Optional[Callable[[], bool]] = None,
    params: Any = None,
) -> List[Dict[str, Any]]:
    attempt = 0
    while True:
        try:
            return client.query(sql, params)
        except Exception as exc:
            if not _is_sqlserver_deadlock_error(exc) or attempt >= len(_DEADLOCK_RETRY_DELAYS_SEC):
                raise
            delay = _DEADLOCK_RETRY_DELAYS_SEC[attempt]
            attempt += 1
            logger.warning(
                "U8 SQLServer deadlock 1205，sleep 后重试: label=%s, attempt=%s/%s, delay=%.1fs",
                log_label,
                attempt,
                len(_DEADLOCK_RETRY_DELAYS_SEC),
                delay,
            )
            raise_if_cancelled(cancel_checker)
            time.sleep(delay)
            raise_if_cancelled(cancel_checker)


def _is_price_missing(value: Any) -> bool:
    """Return True if the price value is NULL, empty, or zero."""
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    try:
        return float(text) == 0
    except Exception:
        return True


def _query_recordoutlist_prices(
    client: Any,
    missing_codes: set[str],
) -> Dict[str, float]:
    """Query recordoutlist for latest iunitcost per cinvcode.

    Returns a dict mapping cinvcode -> iunitcost (latest record per code).
    Falls back to simpler ORDER BY if ddate column is unavailable.
    """
    if not missing_codes:
        return {}

    codes = sorted(missing_codes)
    placeholders = ", ".join(["%s"] * len(codes))

    # Try with ddate first (standard U8 date column), fallback to autoid only
    for order_by in ("ddate DESC, autoid DESC", "autoid DESC"):
        sql = f"""
            SELECT cinvcode, iunitcost
            FROM (
                SELECT
                    cinvcode,
                    iunitcost,
                    ROW_NUMBER() OVER (
                        PARTITION BY cinvcode
                        ORDER BY {order_by}
                    ) AS rn
                FROM UFDATA_CHANGE_ME.dbo.recordoutlist
                WHERE cinvcode IN ({placeholders})
                  AND iunitcost IS NOT NULL
                  AND iunitcost <> 0
            ) t
            WHERE rn = 1
        """
        try:
            rows = _query_with_deadlock_retry(
                client,
                sql,
                log_label=f"recordoutlist_prices:{order_by}",
                params=codes,
            )
            result: Dict[str, float] = {}
            for row in rows:
                code = str(row.get("cinvcode", "")).strip()
                cost = row.get("iunitcost")
                if code and cost is not None:
                    try:
                        result[code] = float(cost)
                    except (ValueError, TypeError):
                        pass
            return result
        except Exception as exc:
            logger.warning(
                "recordoutlist 价格补充查询失败 (ORDER BY %s): %s",
                order_by, exc,
            )
            continue

    logger.warning("recordoutlist 价格补充查询失败 (所有 ORDER BY 回退)")
    return {}


def _supplement_missing_prices(
    result_rows: List[Dict[str, Any]],
    client: Any,
) -> None:
    """Supplement missing iInvNcost from recordoutlist, in-place.

    For every row where iInvNcost is NULL/empty/0, look up the latest
    iunitcost from recordoutlist for that ChildInvCode and fill it in.
    Also recalculate TOTAL_PRICE for supplemented rows.
    """
    missing_codes: set[str] = set()
    for row in result_rows:
        if _is_price_missing(row.get("iInvNcost")):
            code = str(row.get("ChildInvCode") or "").strip()
            if code:
                missing_codes.add(code)

    if not missing_codes:
        return

    supplement_prices = _query_recordoutlist_prices(client, missing_codes)
    if not supplement_prices:
        logger.info("U8 价格补充: recordoutlist 无匹配价格, missing_codes=%s", len(missing_codes))
        return

    supplemented_count = 0
    for row in result_rows:
        if not _is_price_missing(row.get("iInvNcost")):
            continue
        code = str(row.get("ChildInvCode") or "").strip()
        fallback_price = supplement_prices.get(code)
        if fallback_price is None:
            continue

        row["iInvNcost"] = fallback_price

        cum_qty = row.get("CUM_QTY")
        if cum_qty is not None:
            try:
                row["TOTAL_PRICE"] = float(cum_qty) * fallback_price
            except (ValueError, TypeError):
                row["TOTAL_PRICE"] = None

        supplemented_count += 1

    if supplemented_count > 0:
        logger.info(
            "U8 价格补充完成: supplemented=%s/%s missing, queried_codes=%s",
            supplemented_count,
            len(missing_codes),
            len(supplement_prices),
        )


def split_parent_inv_codes(value: Any) -> List[str]:
    """Normalize parent_inv_codes input; dedupe by order."""
    if value is None:
        return []

    codes: List[str] = []
    if isinstance(value, str):
        parts = re.split(r"[;,/|\s、，；]+", value)
        for part in parts:
            code = part.strip()
            if code:
                codes.append(code)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for item in value:
            code = str(item).strip()
            if code:
                codes.append(code)
    else:
        code = str(value).strip()
        if code:
            codes.append(code)

    return list(dict.fromkeys(codes))


def _fetch_root_inv_names(client: SqlServerClient, codes: List[str]) -> Dict[str, str]:
    """批量查询根父件编码对应的名称"""
    if not codes:
        return {}

    # 构建 IN 条件
    placeholders = ", ".join(["%s"] * len(codes))
    sql = f"""
        SELECT cInvCode, cInvName
        FROM Inventory
        WHERE cInvCode IN ({placeholders})
    """
    rows = _query_with_deadlock_retry(
        client,
        sql,
        log_label="root_inv_names",
        params=codes,
    )

    result: Dict[str, str] = {}
    for row in rows:
        code = str(row.get("cInvCode") or "").strip()
        name = str(row.get("cInvName") or "").strip()
        if code and name:
            result[code] = name

    # 找不到名称的编码，使用编码本身作为名称
    for code in codes:
        if code not in result:
            result[code] = code

    return result


def _fill_inventory_only_rows(
    result_rows: List[Dict[str, Any]],
    client: Any,
    no_bom_codes: List[str],
    root_name_map: Dict[str, str],
) -> None:
    """For codes without BOM children (purchased/leaf items), query Inventory
    directly and append a single self-referencing row per code.

    This handles items like 铭牌 (108xxx), 标准件 (104xxx), etc. that are
    purchased parts with no BOM structure — they only exist in Inventory.
    """
    if not no_bom_codes:
        return

    placeholders = ", ".join(["%s"] * len(no_bom_codes))
    sql = f"""
        SELECT
            cInvCode,
            cInvName,
            iInvSprice,
            iInvNcost,
            cInvStd,
            cInvDepCode,
            cDefWareHouse,
            bForeExpland,
            iSupplyType
        FROM Inventory
        WHERE cInvCode IN ({placeholders})
    """
    try:
        inv_rows = _query_with_deadlock_retry(
            client,
            sql,
            log_label="inventory_only_rows",
            params=no_bom_codes,
        )
    except Exception as exc:
        logger.warning("Inventory 采购件回退查询失败: %s", exc)
        return

    # Map code -> inventory row
    inv_by_code: Dict[str, Dict[str, Any]] = {}
    for row in inv_rows:
        code = str(row.get("cInvCode") or "").strip()
        if code:
            inv_by_code[code] = row

    filled_count = 0
    for code in no_bom_codes:
        inv = inv_by_code.get(code)
        if not inv:
            logger.info("U8 采购件回退: 编码 %s 在 Inventory 中无记录", code)
            continue

        inv_cost = inv.get("iInvNcost")
        inv_cost_num = to_float_local(inv_cost, 0.0) if inv_cost is not None else None
        total_price = inv_cost_num if inv_cost_num is not None else None

        result_rows.append(
            {
                "ROOT_INV_CODE": code,
                "ROOT_INV_NAME": root_name_map.get(code, code),
                "ParentInvCode": code,
                "ChildInvCode": code,
                "CHINANAME": inv.get("cInvName"),
                "BomId": None,
                "SortSeq": 1,
                "BaseQtyN": 1,
                "BaseQtyD": 1,
                "COUNTS": 1.0,
                "CUM_QTY": 1.0,
                "LEVEL": 1,
                "CompScrap": None,
                "cInvCode": code,
                "HAS_INVENTORY": "YES",
                "iInvSprice": inv.get("iInvSprice"),
                "iInvNcost": inv.get("iInvNcost"),
                "cInvStd": inv.get("cInvStd"),
                "cInvDepCode": inv.get("cInvDepCode"),
                "cDefWareHouse": inv.get("cDefWareHouse"),
                "bForeExpland": inv.get("bForeExpland"),
                "iSupplyType": inv.get("iSupplyType"),
                "TOTAL_PRICE": total_price,
            }
        )
        filled_count += 1

    if filled_count > 0:
        logger.info(
            "U8 采购件回退完成: filled=%s/%s codes",
            filled_count,
            len(no_bom_codes),
        )


def to_float_local(value: Any, default: float = 0.0) -> float:
    """Local to_float for use outside _query_u8_bom_inventory closure."""
    try:
        return float(value)
    except Exception:
        return default


_BOM_FETCH_CHILDREN_SQL = """
    ;WITH PartMap AS (
        SELECT
            vp.PartId,
            COALESCE(
                NULLIF(LTRIM(RTRIM(vp.InvCode)), ''),
                NULLIF(LTRIM(RTRIM(vp.cInvCode)), '')
            ) AS PartInvCode
        FROM v_bas_part vp
    ),
    RawData AS (
        SELECT
            parent.PartInvCode AS ParentInvCode,
            child.PartInvCode AS ChildInvCode,
            oc.BomId,
            b.ModifyDate,
            b.ModifyTime,
            oc.SortSeq,
            oc.BaseQtyN,
            oc.BaseQtyD,
            oc.CompScrap,
            CAST(1.0 * oc.BaseQtyN / NULLIF(oc.BaseQtyD, 0) AS DECIMAL(38,12)) AS QtyPer,
            ic.cInvName,
            ic.iInvSprice,
            ic.iInvNcost,
            ic.cInvStd,
            ic.cInvDepCode,
            ic.cDefWareHouse,
            ic.bForeExpland,
            ic.iSupplyType,
            child.PartId AS ChildPartId,
            ROW_NUMBER() OVER (
                PARTITION BY parent.PartInvCode, child.PartInvCode
                ORDER BY b.ModifyDate DESC, b.ModifyTime DESC, oc.SortSeq
            ) AS rn
        FROM PartMap parent
        JOIN bom_parent bp ON bp.ParentId = parent.PartId
        JOIN bom_opcomponent oc ON oc.BomId = bp.BomId
        JOIN bom_bom b ON b.BomId = bp.BomId AND b.Status = 3
        JOIN PartMap child ON child.PartId = oc.ComponentId
            LEFT JOIN Inventory ic ON ic.cInvCode = child.PartInvCode
            WHERE parent.PartInvCode = %s
        )
    SELECT
        ParentInvCode, ChildInvCode, BomId, ModifyDate, ModifyTime,
        SortSeq, BaseQtyN, BaseQtyD, CompScrap, QtyPer,
        cInvName, iInvSprice, iInvNcost, cInvStd, cInvDepCode, cDefWareHouse, bForeExpland, iSupplyType, ChildPartId
    FROM RawData
    WHERE rn = 1
    ORDER BY SortSeq, ChildInvCode
"""

_PARTMAP_PROBE_SQL = """
    SELECT
        SUM(CASE WHEN COALESCE(
            NULLIF(LTRIM(RTRIM(vp.InvCode)), ''),
            NULLIF(LTRIM(RTRIM(vp.cInvCode)), '')
        ) = %s THEN 1 ELSE 0 END) AS InvCodeHits,
        SUM(CASE WHEN CAST(vp.PartId AS NVARCHAR(100)) = %s THEN 1 ELSE 0 END) AS PartIdHits
    FROM v_bas_part vp
"""


def _probe_partmap_hits(
    client: Any,
    code: str,
    cancel_checker: Optional[Callable[[], bool]] = None,
) -> Dict[str, Optional[int]]:
    try:
        rows = _query_with_deadlock_retry(
            client,
            _PARTMAP_PROBE_SQL,
            log_label=f"partmap_probe:{code}",
            cancel_checker=cancel_checker,
            params=(code, code),
        )
        first = rows[0] if rows else {}
        inv_hits_raw = first.get("InvCodeHits") if isinstance(first, dict) else None
        part_hits_raw = first.get("PartIdHits") if isinstance(first, dict) else None
        return {
            "inv_code_hits": int(inv_hits_raw) if inv_hits_raw is not None else None,
            "part_id_hits": int(part_hits_raw) if part_hits_raw is not None else None,
        }
    except Exception as exc:
        logger.warning("U8 PartMap 命中探针失败: code=%s, error=%s", code, exc)
        return {"inv_code_hits": None, "part_id_hits": None}


def _fetch_children_cached(
    client: Any,
    cache: "SharedChildrenCache",
    parent_inv_code: str,
    root_codes_set: set[str],
    cancel_checker: Optional[Callable[[], bool]] = None,
) -> List[Dict[str, Any]]:
    """Fetch BOM children for one parent code, using a shared thread-safe cache.

    The SQL fetch runs inside ``cache.get_or_fetch``'s lock, so concurrent
    workers requesting the same parent code block until the first fetch
    completes; the result is then shared globally without re-querying.
    """

    def _do_fetch() -> List[Dict[str, Any]]:
        raise_if_cancelled(cancel_checker)
        _sql_start = time.time()
        rows = _query_with_deadlock_retry(
            client,
            _BOM_FETCH_CHILDREN_SQL,
            log_label=f"fetch_children:{parent_inv_code}",
            cancel_checker=cancel_checker,
            params=(parent_inv_code,),
        )
        _sql_elapsed = time.time() - _sql_start
        _diag_record_sql(_sql_elapsed)
        if not rows and parent_inv_code in root_codes_set:
            probe = _probe_partmap_hits(client, parent_inv_code, cancel_checker)
            logger.warning(
                "U8 根节点无子件: parent_code=%s, inv_code_hits=%s, part_id_hits=%s",
                parent_inv_code,
                probe.get("inv_code_hits"),
                probe.get("part_id_hits"),
            )
        return rows

    _py_start = time.time()
    result = cache.get_or_fetch(parent_inv_code, _do_fetch)
    _diag_record_python(time.time() - _py_start)
    return result


def _walk_bom_subtree(
    *,
    client: Any,
    cache: "SharedChildrenCache",
    root_code: str,
    root_name: str,
    parent_code: str,
    level: int,
    max_depth: int,
    cumulative_qty: float,
    visited_part_ids: set[str],
    root_codes_set: set[str],
    cancel_checker: Optional[Callable[[], bool]] = None,
) -> List[Dict[str, Any]]:
    """Depth-first walk of one BOM subtree; returns rows for this subtree only.

    Uses the provided ``client`` (a pooled connection wrapper) and a shared
    thread-safe ``cache`` so that concurrent workers never share a pymssql
    connection but do share BOM children results across roots.
    """
    if level > max_depth:
        return []

    children = _fetch_children_cached(
        client,
        cache,
        parent_code,
        root_codes_set,
        cancel_checker,
    )
    if not children:
        return []

    result_rows: List[Dict[str, Any]] = []

    for child in children:
        child_part_id = str(child.get("ChildPartId") or "").strip()
        child_inv_code = str(child.get("ChildInvCode") or "").strip()

        if child_part_id and child_part_id in visited_part_ids:
            continue

        qty_per = to_float_local(child.get("QtyPer"), 0.0)
        child_cumulative_qty = cumulative_qty * qty_per
        inv_cost = child.get("iInvNcost")
        inv_cost_num = to_float_local(inv_cost, 0.0) if inv_cost is not None else None
        total_price = child_cumulative_qty * inv_cost_num if inv_cost_num is not None else None

        result_rows.append(
            {
                "ROOT_INV_CODE": root_code,
                "ROOT_INV_NAME": root_name,
                "ParentInvCode": parent_code,
                "ChildInvCode": child_inv_code,
                "CHINANAME": child.get("cInvName"),
                "BomId": child.get("BomId"),
                "SortSeq": child.get("SortSeq"),
                "BaseQtyN": child.get("BaseQtyN"),
                "BaseQtyD": child.get("BaseQtyD"),
                "COUNTS": qty_per,
                "CUM_QTY": child_cumulative_qty,
                "LEVEL": level,
                "CompScrap": child.get("CompScrap"),
                "cInvCode": child_inv_code or None,
                "HAS_INVENTORY": "YES" if child.get("cInvName") else "NO",
                "iInvSprice": child.get("iInvSprice"),
                "iInvNcost": child.get("iInvNcost"),
                "cInvStd": child.get("cInvStd"),
                "cInvDepCode": child.get("cInvDepCode"),
                "cDefWareHouse": child.get("cDefWareHouse"),
                "bForeExpland": child.get("bForeExpland"),
                "iSupplyType": child.get("iSupplyType"),
                "TOTAL_PRICE": total_price,
            }
        )

        next_visited = set(visited_part_ids)
        if child_part_id:
            next_visited.add(child_part_id)

        # 4/7 开头的编码不再继续向下展开
        if child_inv_code and child_inv_code.startswith(("4", "7")):
            continue

        if child_inv_code:
            result_rows.extend(
                _walk_bom_subtree(
                    client=client,
                    cache=cache,
                    root_code=root_code,
                    root_name=root_name,
                    parent_code=child_inv_code,
                    level=level + 1,
                    max_depth=max_depth,
                    cumulative_qty=child_cumulative_qty,
                    visited_part_ids=next_visited,
                    root_codes_set=root_codes_set,
                    cancel_checker=cancel_checker,
                )
            )

    return result_rows


def _walk_one_root(
    root_code: str,
    root_name: str,
    max_depth: int,
    root_codes_set: set[str],
    cancel_checker: Optional[Callable[[], bool]],
    pool: "PymssqlConnectionPool",
    shared_cache: "SharedChildrenCache",
) -> tuple[List[Dict[str, Any]], bool]:
    """Walk one root code's BOM subtree using a dedicated pooled connection.

    Shares ``shared_cache`` across all roots so common subassemblies are
    fetched only once. Returns ``(rows, has_no_bom_children)``.
    """
    raise_if_cancelled(cancel_checker)
    _diag_thread_enter()
    try:
        with pooled_client(pool) as client:
            rows = _walk_bom_subtree(
                client=client,
                cache=shared_cache,
                root_code=root_code,
                root_name=root_name,
                parent_code=root_code,
                level=1,
                max_depth=max_depth,
                cumulative_qty=1.0,
                visited_part_ids=set(),
                root_codes_set=root_codes_set,
                cancel_checker=cancel_checker,
            )
        return rows, len(rows) == 0
    finally:
        _diag_thread_exit()


def _query_u8_bom_inventory(
    parent_codes: List[str],
    max_depth: int,
    cancel_checker: Optional[Callable[[], bool]] = None,
) -> List[Dict[str, Any]]:
    if not parent_codes:
        return []

    parallel_workers = max(1, min(settings.U8_BOM_PARALLEL_WORKERS, len(parent_codes)))
    pool_config = {
        "backend": "pymssql",
        "server": settings.U8_SQLSERVER_HOST,
        "port": settings.U8_SQLSERVER_PORT,
        "database": settings.U8_SQLSERVER_DATABASE,
        "username": settings.U8_SQLSERVER_USER,
        "password": settings.U8_SQLSERVER_PASSWORD,
        "encrypt": settings.U8_SQLSERVER_ENCRYPT,
    }

    slot_held = False
    pool: Optional[PymssqlConnectionPool] = None
    overall_start = time.time()

    try:
        # 获取 BOM 并发槽位（信号量），限制同时运行的 BOM 任务数以保护 U8 ERP 库。
        # 在排队等待期间支持取消。acquire 在 try 内，确保后续任何异常都能在 finally 释放槽位。
        _acquire_bom_slot(cancel_checker)
        slot_held = True

        pool = get_sql_client_pool(pool_config, max_size=parallel_workers)
        root_codes_set = set(parent_codes)
        shared_cache = SharedChildrenCache()

        logger.info(
            "U8 BOM 并行查询开始: root_codes=%s, parallel_workers=%s, max_depth=%s",
            len(parent_codes),
            parallel_workers,
            max_depth,
        )
        _diag_reset()

        # 1. 批量查询所有根父件名称（单连接）
        with pooled_client(pool) as name_client:
            root_name_map = _fetch_root_inv_names(name_client, parent_codes)

        # 2. 展开每个根编码的 BOM 子树（并行或串行回退）
        # 结果按 parent_codes 输入顺序归并，保证与原串行实现输出顺序一致。
        per_root_rows: Dict[str, List[Dict[str, Any]]] = {}
        per_root_no_bom: set[str] = set()

        if parallel_workers == 1:
            # 串行回退路径（显式禁用并行或仅单个根编码）
            for root_code in parent_codes:
                raise_if_cancelled(cancel_checker)
                root_name = root_name_map.get(root_code, root_code)
                rows, no_bom = _walk_one_root(
                    root_code, root_name, max_depth, root_codes_set,
                    cancel_checker, pool, shared_cache,
                )
                per_root_rows[root_code] = rows
                if no_bom:
                    per_root_no_bom.add(root_code)
                logger.info("U8 根节点展开完成: root_code=%s, rows=%s", root_code, len(rows))
        else:
            with ThreadPoolExecutor(
                max_workers=parallel_workers, thread_name_prefix="u8_bom_"
            ) as ex:
                future_map = {
                    ex.submit(
                        _walk_one_root,
                        root_code,
                        root_name_map.get(root_code, root_code),
                        max_depth,
                        root_codes_set,
                        cancel_checker,
                        pool,
                        shared_cache,
                    ): root_code
                    for root_code in parent_codes
                }
                for future in as_completed(future_map):
                    root_code = future_map[future]
                    try:
                        rows, no_bom = future.result()
                    except QueryCancelledError:
                        # 取消：取消其余未完成的 future 后向上抛出
                        for f in future_map:
                            f.cancel()
                        raise
                    except Exception as exc:
                        # fail-fast：取消兄弟任务，避免继续浪费 DB 负载
                        logger.error(
                            "U8 根节点展开异常: root_code=%s, error=%s",
                            root_code,
                            exc,
                            exc_info=True,
                        )
                        for f in future_map:
                            f.cancel()
                        raise
                    per_root_rows[root_code] = rows
                    if no_bom:
                        per_root_no_bom.add(root_code)
                    logger.info("U8 根节点展开完成: root_code=%s, rows=%s", root_code, len(rows))

        # 按输入顺序合并结果，保持与原串行实现一致的输出顺序
        result_rows: List[Dict[str, Any]] = []
        no_bom_root_codes: List[str] = []
        for root_code in parent_codes:
            result_rows.extend(per_root_rows.get(root_code, []))
            if root_code in per_root_no_bom:
                no_bom_root_codes.append(root_code)

        _diag_log_summary("并行展开阶段")

        _diag_log_summary("BOM 并行展开")

        _diag_log_summary("BOM 并行展开")

        # 3. 无 BOM 子件的根编码 → 直接查 Inventory（单连接批量）
        with pooled_client(pool) as inv_client:
            _fill_inventory_only_rows(
                result_rows, inv_client, no_bom_root_codes, root_name_map
            )

        # 4. 补充缺失价格（单连接批量）
        with pooled_client(pool) as price_client:
            _supplement_missing_prices(result_rows, price_client)

        elapsed = time.time() - overall_start
        logger.info(
            "U8 BOM 并行查询完成: root_codes=%s, total_rows=%s, elapsed=%.2fs, "
            "parallel_workers=%s, pool_created=%s",
            len(parent_codes),
            len(result_rows),
            elapsed,
            parallel_workers,
            pool.created_count,
        )
        return result_rows
    finally:
        if pool is not None:
            pool.close()
        if slot_held:
            _release_bom_slot()
            slot_held = False


_SUPPLY_TYPE_MAP: Dict[int, str] = {
    0: "领用",
    1: "入库倒冲",
    2: "工序倒冲",
    3: "虚拟件",
    4: "直接供应",
}


def _determine_supply_type(row: Dict[str, Any]) -> str:
    """Determine supply type from iSupplyType, falling back to bForeExpland,
    then to iInvNcost-based heuristic.

    Priority:
    1. Inventory.iSupplyType (from U8 AA_Enum: 0=领用, 1=入库倒冲, 2=工序倒冲, 3=虚拟件, 4=直接供应)
    2. Inventory.bForeExpland (1=虚拟件)
    3. iInvNcost heuristic (non-zero → 领用, else → 虚拟件)
    """
    # 1. Try iSupplyType
    iSupplyType = row.get("iSupplyType")
    if iSupplyType is not None:
        try:
            return _SUPPLY_TYPE_MAP[int(iSupplyType)]
        except (ValueError, TypeError, KeyError):
            pass

    # 2. Try bForeExpland
    bForeExpland = row.get("bForeExpland")
    if bForeExpland is not None:
        try:
            return "虚拟件" if int(bForeExpland) == 1 else "领用"
        except (ValueError, TypeError):
            pass

    # 3. Fallback to cost-based heuristic
    return "领用" if _is_material_item_by_cost(row.get("iInvNcost")) else "虚拟件"


def format_u8_output_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map U8 raw rows to the slim fields used for export/save."""

    formatted_rows: List[Dict[str, Any]] = []
    for row in rows:
        supply_type = _determine_supply_type(row)
        formatted_rows.append(
            {
                "子件层级": row.get("LEVEL"),
                "子件名称": row.get("CHINANAME"),
                "根父件名称": row.get("ROOT_INV_NAME"),
                "材料编码（物料编码）": row.get("cInvCode"),
                "累计用量": row.get("CUM_QTY"),
                "供应类型": supply_type,
                "规格型号": row.get("cInvStd"),
                "单价": row.get("iInvNcost"),
                "总价": row.get("TOTAL_PRICE"),
                "__root_inv_code": row.get("ROOT_INV_CODE"),
                "__root_inv_name": row.get("ROOT_INV_NAME"),
                "__parent_inv_code": row.get("ParentInvCode"),
            }
        )

    return formatted_rows


def _is_material_item_by_cost(value: Any) -> bool:
    """Fallback check: item with a non-zero cost price is a real material item."""
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    try:
        return float(text) != 0
    except Exception:
        return False
