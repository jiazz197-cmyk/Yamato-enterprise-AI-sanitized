from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
import logging
from urllib.parse import unquote

from app.integrations.context_compression import LlmEndpointMisconfiguredError, compress_context
from app.schemas.base import FormatJSONResponse
from app.core.security import get_current_user, normalize_self_user_identifier
from app.models.orm.platform.user import User
from app.models.orm.platform.user import UserRole

logger = logging.getLogger(__name__)
router = APIRouter()

class ContextCompressionRequest(BaseModel):
    user_id: str = Field(..., description="User ID for fetching conversation")
    conversation_id: str = Field(..., description="Dify conversation ID")
    n_recent: int = Field(5, description="Number of recent dialogue turns to keep")

@router.post("/compress")
def compress_chat_context(
    request: ContextCompressionRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Compress chat context based on Dify conversation ID.
    The result includes:
    1. Working context (Recent N turns)
    2. Session summary (Older messages)
    3. Durable memory
    Total length will be between 500-700 words.
    """
    try:
        decoded_user_id = unquote(request.user_id).strip()
        logger.info(
            "Received context compression request for conversation %s from user %s",
            request.conversation_id,
            decoded_user_id,
        )

        context_data = request.model_dump()
        if current_user.role == UserRole.superuser:
            # superuser can run compression for any target user
            effective_user_id = decoded_user_id
        else:
            # normal users can only access their own identity aliases
            normalize_self_user_identifier(decoded_user_id, current_user)
            effective_user_id = decoded_user_id

        # Dify variables endpoint expects business user_id, not auth UUID.
        context_data["user_id"] = effective_user_id
        compressed_result = compress_context(context_data)

        return FormatJSONResponse(
            data={"compressed_context": compressed_result},
            message="Context compressed successfully",
        )
    except LlmEndpointMisconfiguredError as e:
        logger.warning(
            "Context compression misconfigured for conversation %s: %s",
            request.conversation_id,
            str(e)[:500],
        )
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        logger.error("Failed to compress context for conversation %s: %s", request.conversation_id, str(e)[:2000])
        raise HTTPException(
            status_code=500,
            detail="Failed to compress context",
        ) from e
