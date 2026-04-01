"""
Chat Summary API Endpoints
Provides endpoints for managing user chat summaries
"""
from fastapi import APIRouter, HTTPException, Depends, status
import logging
import uuid
from sqlalchemy.orm import Session

from app.schemas.base import (
    ChatSummaryRequest,
    ChatSummaryResponse,
    UserSummaryResponse,
    FormatJSONResponse
)
from app.integrations.Chat_message_archive.message_extractor import (
    update_user_profile_with_new_queries,
    UserProfileDB
)
from app.core.config import settings
from app.core.dependencies import get_db
from app.core.security import get_current_user, normalize_self_user_identifier
from app.models.orm.platform.user import User, UserRole

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/create", response_model=ChatSummaryResponse)
def create_chat_summary(
    request: ChatSummaryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create or update user chat summary

    This endpoint:
    1. Extracts queries from the specified conversation
    2. Gets user's previous summary (if exists)
    3. Generates new summary using LLM
    4. Updates database with new summary

    Args:
        request: ChatSummaryRequest containing user_id, conversation_id, and optional limit

    Returns:
        ChatSummaryResponse with operation results

    Example:
        POST /api/v1/chat-summary/create
        {
            "user_id": "abc-123",
            "conversation_id": "cd78daf6-f9e4-4463-9ff2-54257230a0ce",
            "limit": 20
        }
    """
    try:
        request_user_id = request.user_id.strip()
        current_aliases = {
            str(current_user.id).strip(),
            (current_user.username or "").strip(),
            (getattr(current_user, "name", "") or "").strip(),
        }
        current_aliases.discard("")

        if request_user_id in current_aliases:
            # 本人操作统一落到 username，避免 UUID 与 username 键不一致
            request_user_id = (current_user.username or "").strip() or str(current_user.id)
        elif current_user.role != UserRole.superuser:
            # 普通用户仅允许本人
            normalize_self_user_identifier(request_user_id, current_user)
            request_user_id = (current_user.username or "").strip() or str(current_user.id)
        else:
            # 管理员代查/代写：若传 UUID，自动转换为目标用户 username
            try:
                lookup_uuid = uuid.UUID(request_user_id)
                target_user = db.query(User).filter(User.id == lookup_uuid).first()
                if target_user:
                    request_user_id = (target_user.username or "").strip() or str(target_user.id)
            except ValueError:
                # 非 UUID，默认按传入 user_id（如 username）查询
                pass

        logger.info(f"Creating chat summary for user {request_user_id}, conversation {request.conversation_id}")

        # 使用配置中的 CHAT_API_KEY，禁止硬编码
        result = update_user_profile_with_new_queries(
            api_key=settings.CHAT_API_KEY,
            user_id=request_user_id,
            conversation_id=request.conversation_id,
            limit=request.limit
        )

        # Build response
        response_data = {
            "user_id": result["user_id"],
            "conversation_id": result["conversation_id"],
            "query_count": result["query_count"],
            "previous_summary": result["previous_summary"],
            "new_summary": result["new_summary"],
            "is_first_time": result["is_first_time"],
            "db_updated": result["db_updated"]
        }

        if not result["db_updated"]:
            logger.warning(f"Failed to update database for user {request.user_id}")

        return FormatJSONResponse(
            data=response_data,
            message="Chat summary created successfully" if result["db_updated"] else "Summary generated but database update failed"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create chat summary: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to create chat summary"
        )


@router.get("/query/{user_id}", response_model=UserSummaryResponse)
def query_user_summary(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Query user's latest chat summary

    This endpoint retrieves the latest summary for a specific user from the database.

    Args:
        user_id: User identifier

    Returns:
        UserSummaryResponse with user's latest summary

    Example:
        GET /api/v1/chat-summary/query/abc-123
    """
    try:
        target_user_id = user_id.strip()
        current_aliases = {
            str(current_user.id).strip(),
            (current_user.username or "").strip(),
            (getattr(current_user, "name", "") or "").strip(),
        }
        current_aliases.discard("")

        if target_user_id in current_aliases:
            # 本人查询统一落到 username
            target_user_id = (current_user.username or "").strip() or str(current_user.id)
        elif current_user.role != UserRole.superuser:
            # 普通用户仅允许本人
            normalize_self_user_identifier(target_user_id, current_user)
            target_user_id = (current_user.username or "").strip() or str(current_user.id)
        else:
            # 管理员查询：若传 UUID，自动转换为目标用户 username
            try:
                lookup_uuid = uuid.UUID(target_user_id)
                target_user = db.query(User).filter(User.id == lookup_uuid).first()
                if target_user:
                    target_user_id = (target_user.username or "").strip() or str(target_user.id)
            except ValueError:
                # 非 UUID，默认按传入 user_id（如 username）查询
                pass

        logger.info(f"Querying summary for user {target_user_id}")

        # Initialize database connection with default settings
        db = UserProfileDB()

        # Get latest summary
        latest_summary = db.get_latest_summary(target_user_id)

        # Build response
        response_data = {
            "user_id": target_user_id,
            "latest_summary": latest_summary,
            "exists": latest_summary is not None
        }

        return FormatJSONResponse(
            data=response_data,
            message="User summary found" if latest_summary else "No summary found for this user"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to query user summary: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to query user summary"
        )
