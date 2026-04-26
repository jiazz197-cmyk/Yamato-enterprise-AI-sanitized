"""SQL Server client factory (pymssql or sqlserver_tools)."""

from __future__ import annotations

from typing import Any, Dict, List

from app.core.config import settings
from app.core.exceptions import ExternalServiceError


def get_sql_client(config: Dict[str, Any]):
    """Prefer sqlserver_tools, fall back to pymssql."""
    try:
        from sqlserver_tools import ConnectionConfig, SqlServerClient  # type: ignore

        return SqlServerClient(ConnectionConfig(**config))
    except ImportError:
        pass

    try:
        import pymssql  # type: ignore
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
                self._conn = pymssql.connect(
                    server=self.conf["server"],
                    port=self.conf.get("port", 1433),
                    user=self.conf["username"],
                    password=self.conf["password"],
                    database=self.conf["database"],
                    charset="utf8",
                    as_dict=True,
                    timeout=settings.SQLSERVER_QUERY_TIMEOUT_SEC,
                    login_timeout=settings.SQLSERVER_LOGIN_TIMEOUT_SEC,
                )
            return self._conn

        def query(self, sql: str) -> List[Dict[str, Any]]:
            try:
                conn = self._ensure_conn()
                with conn.cursor(as_dict=True) as cursor:
                    cursor.execute(sql)
                    rows = cursor.fetchall()
                return [dict(row) for row in rows]
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
