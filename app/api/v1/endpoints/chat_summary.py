"""
Chat Summary API Endpoints
Provides endpoints for managing user chat summaries
"""
from fastapi import APIRouter, HTTPException
import logging

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

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/create", response_model=ChatSummaryResponse)
def create_chat_summary(request: ChatSummaryRequest):
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
        logger.info(f"Creating chat summary for user {request.user_id}, conversation {request.conversation_id}")
        
        # Call the message extractor function with default settings
        result = update_user_profile_with_new_queries(
            api_key=settings.CHAT_API_KEY,
            user_id=request.user_id,
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
        
    except Exception as e:
        logger.error(f"Failed to create chat summary: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create chat summary: {str(e)}"
        )


@router.get("/query/{user_id}", response_model=UserSummaryResponse)
def query_user_summary(user_id: str):
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
        logger.info(f"Querying summary for user {user_id}")
        
        # Initialize database connection with default settings
        db = UserProfileDB()
        
        # Get latest summary
        latest_summary = db.get_latest_summary(user_id)
        
        # Build response
        response_data = {
            "user_id": user_id,
            "latest_summary": latest_summary,
            "exists": latest_summary is not None
        }
        
        return FormatJSONResponse(
            data=response_data,
            message="User summary found" if latest_summary else "No summary found for this user"
        )
        
    except Exception as e:
        logger.error(f"Failed to query user summary: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query user summary: {str(e)}"
        )
