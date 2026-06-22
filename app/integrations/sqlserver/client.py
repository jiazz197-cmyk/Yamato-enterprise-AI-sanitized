"""SQL Server client factory (pymssql or sqlserver_tools).

提供两种 client：
- ``get_sql_client``：单连接 client（向后兼容，单线程顺序查询场景）。
- ``get_sql_client_pool``：连接池，供多线程并行查询使用，每个工作线程独占一条连接。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from app.core.config import settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger

logger = get_logger("database.sqlserver.client")


def _build_pymssql_conn(conf: Dict[str, Any]) -> Any:
    import pymssql  # type: ignore

    return pymssql.connect(
        server=conf["server"],
        port=conf.get("port", 1433),
        user=conf["username"],
        password=conf["password"],
        database=conf["database"],
        charset="utf8",
        as_dict=True,
        timeout=settings.SQLSERVER_QUERY_TIMEOUT_SEC,
        login_timeout=settings.SQLSERVER_LOGIN_TIMEOUT_SEC,
    )


def _run_pymssql_query(conn: Any, sql: str, params: Any = None) -> List[Dict[str, Any]]:
    """Execute one query on a raw pymssql connection and return rows as dicts.

    Shared by ``_PymssqlClient`` (single-connection) and ``_PooledConnClient``
    (pooled-connection) so cursor/row-conversion logic stays in one place.
    """
    with conn.cursor(as_dict=True) as cursor:
        if params is None:
            cursor.execute(sql)
        else:
            cursor.execute(sql, params)
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_sql_client(config: Dict[str, Any]):
    """Prefer sqlserver_tools, fall back to pymssql."""
    try:
        from sqlserver_tools import ConnectionConfig, SqlServerClient  # type: ignore

        return SqlServerClient(ConnectionConfig(**config))
    except ImportError:
        pass

    try:
        import pymssql  # type: ignore  # noqa: F401
    except ImportError as exc:
        raise ExternalServiceError(
            "SQLServer",
            "缺少依赖，请安装 sqlserver_tools 或 pymssql",
        ) from exc

    class _PymssqlClient:
        """Reuses a single pymssql connection across queries to avoid repeated
        TCP/TLS/auth handshakes (each handshake costs multiple seconds)."""

        def __init__(self, conf: Dict[str, Any]):
            self.conf = conf
            self._conn: Any = None

        def _ensure_conn(self) -> Any:
            if self._conn is None:
                self._conn = _build_pymssql_conn(self.conf)
            return self._conn

        def query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
            try:
                conn = self._ensure_conn()
                return _run_pymssql_query(conn, sql, params)
            except Exception:
                self.close()
                raise

        def close(self) -> None:
            conn = self._conn
            self._conn = None
            if conn is None:
                return
            try:
                conn.close()
            except Exception:
                pass

        def __enter__(self) -> "_PymssqlClient":
            return self

        def __exit__(self, exc_type, exc_val, exc_tb) -> None:
            self.close()

    return _PymssqlClient(config)


class PymssqlConnectionPool:
    """Thread-safe pool of pymssql connections.

    Each ``acquire()`` returns a dedicated connection (creating one if the pool
    is empty); ``release(conn)`` returns it for reuse. ``close()`` shuts every
    idle connection. Connections that error out should be discarded via
    ``discard(conn)`` rather than released.

    Intended for parallel BOM-tree expansion: every worker thread checks out
    its own connection so queries do not serialize on a single connection.
    """

    def __init__(self, conf: Dict[str, Any], max_size: Optional[int] = None):
        self._conf = conf
        self._max_size = max_size or settings.U8_BOM_PARALLEL_WORKERS
        self._idle: List[Any] = []
        self._lock = threading.Lock()
        self._created_count = 0
        self._closed = False

    def acquire(self) -> Any:
        with self._lock:
            if self._closed:
                raise RuntimeError("连接池已关闭")
            if self._idle:
                conn = self._idle.pop()
                return conn
            if self._created_count >= self._max_size:
                raise RuntimeError(
                    f"连接池已达上限 {self._max_size}，无法再创建新连接"
                )
            self._created_count += 1
        # 建连在锁外执行，避免长时间持锁阻塞其他线程
        try:
            return _build_pymssql_conn(self._conf)
        except Exception:
            with self._lock:
                self._created_count -= 1
            raise

    def release(self, conn: Any) -> None:
        if conn is None:
            return
        with self._lock:
            if self._closed:
                _safe_close(conn)
                return
            self._idle.append(conn)

    def discard(self, conn: Any) -> None:
        """Drop a broken connection: close it and decrement the created counter."""
        if conn is None:
            return
        with self._lock:
            if self._created_count > 0:
                self._created_count -= 1
        _safe_close(conn)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            idle = self._idle
            self._idle = []
        for conn in idle:
            _safe_close(conn)
        logger.debug(
            "PymssqlConnectionPool closed: created_total=%s", self._created_count
        )

    @property
    def created_count(self) -> int:
        with self._lock:
            return self._created_count

    @property
    def idle_count(self) -> int:
        with self._lock:
            return len(self._idle)

    def __enter__(self) -> "PymssqlConnectionPool":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def _safe_close(conn: Any) -> None:
    try:
        conn.close()
    except Exception:
        pass


def get_sql_client_pool(config: Dict[str, Any], max_size: Optional[int] = None) -> "PymssqlConnectionPool":
    """Build a pymssql connection pool for parallel queries.

    Always uses pymssql (sqlserver_tools wrapper is single-connection oriented).
    Raises ExternalServiceError if pymssql is unavailable.
    """
    try:
        import pymssql  # type: ignore  # noqa: F401
    except ImportError as exc:
        raise ExternalServiceError(
            "SQLServer",
            "缺少 pymssql 依赖，无法创建连接池",
        ) from exc
    return PymssqlConnectionPool(config, max_size=max_size)


class _PooledConnClient:
    """Adapter exposing the same ``.query()`` interface as ``_PymssqlClient``,
    backed by a raw pooled pymssql connection.

    Unlike ``_PymssqlClient``, ``close()`` is a no-op — the connection lifecycle
    is managed by the surrounding ``pooled_client`` context manager (which
    releases on success / discards on error). Query errors are NOT auto-closed
    here so that deadlock-retry loops can reuse the same connection.
    """

    def __init__(self, conn: Any):
        self._conn = conn

    def query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
        return _run_pymssql_query(self._conn, sql, params)

    def close(self) -> None:
        pass  # lifecycle managed by pool


@contextmanager
def pooled_client(pool: "PymssqlConnectionPool") -> Iterator[_PooledConnClient]:
    """Check out a connection from ``pool`` and yield a ``.query()``-compatible client.

    On normal exit the connection is returned to the pool; on exception it is
    discarded (closed + counter decremented) so broken connections are not reused.
    """
    conn = pool.acquire()
    client = _PooledConnClient(conn)
    try:
        yield client
    except Exception:
        pool.discard(conn)
        raise
    else:
        pool.release(conn)


def close_sql_client(client: Any) -> None:
    """Best-effort close for any sql client shape (pymssql wrapper or sqlserver_tools)."""
    if client is None:
        return
    closer = getattr(client, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            pass
