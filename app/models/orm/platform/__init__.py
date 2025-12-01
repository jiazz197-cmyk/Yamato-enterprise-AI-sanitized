"""平台模型统一导出"""
from app.models.orm.platform.base import Base
from app.models.orm.platform.user import User, UserLoginHistory, UserPreferences, UserSubscription
from app.models.orm.platform.role import Role
from app.models.orm.platform.permission import Permission
from app.models.orm.platform.user_role import user_role_table
from app.models.orm.platform.role_permission import role_permission_table
from app.models.orm.platform.project import (
    ProjectSpace, ProjectMember, ProjectTask, DataShare,
    ProjectStatus, TaskStatus, TaskPriority
)
from app.models.orm.platform.audit_log import PlatformAuditLog
from app.models.orm.platform.migration_log import MigrationLog, MigrationBackup

__all__ = [
    # Base
    "Base",
    # 用户相关
    "User", "UserLoginHistory", "UserPreferences", "UserSubscription",
    # 角色权限
    "Role", "Permission", "user_role_table", "role_permission_table",
    # 项目空间
    "ProjectSpace", "ProjectMember", "ProjectTask", "DataShare",
    "ProjectStatus", "TaskStatus", "TaskPriority",
    # 日志
    "PlatformAuditLog", "MigrationLog", "MigrationBackup",
]
