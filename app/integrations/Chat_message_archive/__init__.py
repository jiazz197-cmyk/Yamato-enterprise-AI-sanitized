"""
Chat Message Archive Integration

Local message store + LLM summarization (messages read from the local
``messages`` table; no Dify).
"""

from .message_extractor import (
    UserProfileDB,
    fetch_user_queries,
    summarize_queries_with_llm,
    summarize_user_queries,
    update_user_profile_with_new_queries,
)

__all__ = [
    "UserProfileDB",
    "fetch_user_queries",
    "summarize_queries_with_llm",
    "summarize_user_queries",
    "update_user_profile_with_new_queries",
]
