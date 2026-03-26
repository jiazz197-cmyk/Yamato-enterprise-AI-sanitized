from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
import logging

from app.integrations.context_compression import compress_context
from app.schemas.base import FormatJSONResponse
from app.core.security import get_current_user
from app.models.orm.platform.user import User

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
        logger.info(f"Received context compression request for conversation {request.conversation_id} from user {request.user_id}")
        
        # Ensure user can only access their own data or is a superuser (optional, but good practice)
        # normalize_self_user_identifier(request.user_id, current_user)
        
        context_data = request.model_dump()
        compressed_result = compress_context(context_data)
        
        return FormatJSONResponse(
            data={"compressed_context": compressed_result},
            message="Context compressed successfully"
        )
    except Exception as e:
        logger.error(f"Failed to compress context for conversation {request.conversation_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to compress context: {str(e)}"
        )
