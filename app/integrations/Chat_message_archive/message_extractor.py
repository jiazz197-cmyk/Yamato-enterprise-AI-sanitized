"""
Chat Message Archive - Message Extractor
This module extracts query text from chat messages via Dify API
and summarizes user query patterns using LLM
"""

# Add project root to Python path for standalone execution
import sys
from pathlib import Path

# Only add to path if running as script (not when imported as module)
if __name__ == "__main__" or __package__ is None:
    current_file = Path(__file__).resolve()
    project_root = current_file.parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

import requests
from typing import Optional, List, Dict, Any
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.core.config import settings

logger = logging.getLogger(__name__)


class UserProfileDB:
    """
    Manage user chat profile database operations
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None
    ):
        """
        Initialize database connection parameters
        
        Args:
            host: Database host (defaults to settings.POSTGRES_SERVER)
            port: Database port (defaults to settings.POSTGRES_PORT)
            database: Database name (defaults to settings.POSTGRES_DB)
            user: Database user (defaults to settings.POSTGRES_USER)
            password: Database password (defaults to settings.POSTGRES_PASSWORD)
        """
        self.connection_params = {
            'host': host or settings.POSTGRES_SERVER,
            'port': port or settings.POSTGRES_PORT,
            'database': database or settings.POSTGRES_DB,
            'user': user or settings.POSTGRES_USER,
            'password': password or settings.POSTGRES_PASSWORD
        }
    
    def get_connection(self):
        """
        Get a new database connection

        Returns:
            psycopg2 connection object
        """
        try:
            conn = psycopg2.connect(**self.connection_params)
            return conn
        except psycopg2.Error as e:
            logger.error(f"Failed to connect to database: {str(e)}")
            raise

    def ensure_profile_table(self, conn) -> None:
        """确保 user_chat_profile 表存在，避免开发环境首次启动时报错。"""
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_chat_profile (
                    user_id VARCHAR(128) PRIMARY KEY,
                    latest_summary TEXT,
                    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        conn.commit()

    def get_latest_summary(self, user_id: str) -> Optional[str]:
        """
        Get the latest summary for a user
        
        Args:
            user_id: User identifier
            
        Returns:
            Latest summary string or None if user doesn't exist
        """
        conn = None
        try:
            conn = self.get_connection()
            self.ensure_profile_table(conn)
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT latest_summary FROM user_chat_profile WHERE user_id = %s",
                    (user_id,)
                )
                result = cursor.fetchone()
                
                if result:
                    logger.info(f"Found existing summary for user {user_id}")
                    return result['latest_summary']
                else:
                    logger.info(f"No existing summary for user {user_id}")
                    return None
                    
        except psycopg2.Error as e:
            logger.error(f"Failed to get latest summary for user {user_id}: {str(e)}")
            return None
        finally:
            if conn:
                conn.close()
    
    def upsert_latest_summary(self, user_id: str, latest_summary: str) -> bool:
        """
        Insert or update the latest summary for a user
        
        Args:
            user_id: User identifier
            latest_summary: New summary to save
            
        Returns:
            True if successful, False otherwise
        """
        conn = None
        try:
            conn = self.get_connection()
            self.ensure_profile_table(conn)
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_chat_profile (user_id, latest_summary, update_time)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                        latest_summary = EXCLUDED.latest_summary,
                        update_time = EXCLUDED.update_time
                """, (user_id, latest_summary, datetime.now()))

                conn.commit()
                logger.info(f"Successfully updated summary for user {user_id}")
                return True
                
        except psycopg2.Error as e:
            logger.error(f"Failed to upsert summary for user {user_id}: {str(e)}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()


class MessageExtractor:
    """
    Extract query text from Dify conversation API
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: int = 30
    ):
        """
        Initialize the message extractor
        
        Args:
            api_key: API authorization key
            base_url: Base URL for the API endpoint
            timeout: Request timeout in seconds (default: 30)
        """
        self.api_key = api_key
        resolved_base_url = base_url or settings.DIFY_BASE_URL
        resolved_base_url = resolved_base_url.rstrip("/")
        if not resolved_base_url.endswith("/v1"):
            resolved_base_url = f"{resolved_base_url}/v1"

        self.base_url = resolved_base_url
        self.timeout = timeout
        self.headers = {
            'Authorization': f'Bearer {api_key}'
        }
    
    def get_messages(
        self, 
        user_id: str, 
        conversation_id: str, 
        limit: int = 20
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch messages from the API
        
        Args:
            user_id: User identifier
            conversation_id: Conversation identifier
            limit: Maximum number of messages to retrieve
            
        Returns:
            Dictionary containing the API response or None if request fails
        """
        url = f"{self.base_url}/messages"
        params = {
            'user': user_id,
            'conversation_id': conversation_id,
            'limit': limit
        }
        
        try:
            logger.info(f"Fetching messages from {url} with params: {params}")
            response = requests.get(
                url, 
                headers=self.headers, 
                params=params, 
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            logger.error(f"Request timeout after {self.timeout} seconds")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch messages: {str(e)}")
            return None
    
    def extract_queries(
        self, 
        user_id: str, 
        conversation_id: str, 
        limit: int = 20
    ) -> List[str]:
        """
        Extract query text from messages
        
        Args:
            user_id: User identifier
            conversation_id: Conversation identifier
            limit: Maximum number of messages to retrieve
            
        Returns:
            List of query strings
        """
        messages_data = self.get_messages(user_id, conversation_id, limit)
        
        if not messages_data:
            logger.warning("No messages data retrieved")
            return []
        
        queries = []
        data_list = messages_data.get('data', [])
        
        for message in data_list:
            query = message.get('query')
            if query:
                queries.append(query)
        
        logger.info(f"Extracted {len(queries)} queries from conversation {conversation_id}")
        return queries
    
    def summarize_queries_with_llm(
        self, 
        queries: List[str],
        previous_summary: Optional[str] = None,
        llm_base_url: str = "http://localhost:80/llm/qwen8b/v1",
        model_name: str = "Qwen/Qwen3-8B-FP8",
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> str:
        """
        Summarize user query patterns using LLM, optionally incorporating previous summary
        
        Args:
            queries: List of query strings to analyze
            previous_summary: Previous summary to build upon (optional)
            llm_base_url: Base URL for the local LLM API
            model_name: Model name for the LLM
            temperature: Temperature for LLM generation (0.0-1.0)
            max_tokens: Maximum tokens for LLM response
            
        Returns:
            Summary string of user query habits and needs
        """
        if not queries:
            logger.warning("No queries to summarize")
            return "No queries available for analysis."
        
        # Initialize ChatOpenAI with local LLM
        try:
            llm = ChatOpenAI(
                base_url=llm_base_url,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                api_key="not-needed"  # Local model doesn't need API key
            )
            
            # Create prompt template based on whether previous summary exists
            if previous_summary:
                prompt = ChatPromptTemplate.from_messages([
                    ("system", """/nothink 你是一位专业的数据分析师。你的任务是基于用户之前的聊天习惯总结，结合新的提问记录，更新用户的提问习惯和需求总结。
                
                                请从以下几个方面进行分析：
                                1. 用户主要关注的话题和领域（对比之前是否有变化）
                                2. 提问的风格和特点（例如：简短直接、详细描述、偏好某种类型的问题等）
                                3. 可能的业务需求或使用场景
                                4. 新的模式或趋势

                                请用简洁的中文总结，控制在150字以内。注意要整合之前的总结和新的提问记录。"""),
                    ("human", """用户之前的聊天习惯总结：
{previous_summary}

以下是用户最新的{count}条提问记录：
{queries}

请基于之前的总结和新的提问记录，生成更新后的用户聊天习惯总结。""")
                ])
                
                queries_text = "\n".join([f"{i+1}. {q}" for i, q in enumerate(queries)])
                
                logger.info(f"Updating summary with {len(queries)} new queries and previous summary")
                summary = (prompt | llm | StrOutputParser()).invoke({
                    "previous_summary": previous_summary,
                    "count": len(queries),
                    "queries": queries_text
                })
            else:
                prompt = ChatPromptTemplate.from_messages([
                    ("system", """/nothink 你是一位专业的数据分析师。你的任务是分析用户的提问记录，总结他们的提问习惯和需求。
                
                                请从以下几个方面进行分析：
                                1. 用户主要关注的话题和领域
                                2. 提问的风格和特点（例如：简短直接、详细描述、偏好某种类型的问题等）
                                3. 可能的业务需求或使用场景
                                4. 其他值得注意的模式

                                请用简洁的中文总结，控制在150字以内。"""),
                    ("human", """以下是用户的{count}条提问记录：

{queries}

请分析并总结用户的提问习惯和需求。""")
                ])
                
                queries_text = "\n".join([f"{i+1}. {q}" for i, q in enumerate(queries)])
                
                logger.info(f"Creating new summary from {len(queries)} queries")
                summary = (prompt | llm | StrOutputParser()).invoke({
                    "count": len(queries),
                    "queries": queries_text
                })
            
            logger.info("Successfully generated summary")
            return summary
            
        except Exception as e:
            logger.error(f"Failed to summarize queries with LLM: {str(e)}")
            return f"Error generating summary: {str(e)}"


def summarize_user_queries(
    api_key: str,
    user_id: str,
    conversation_id: str,
    limit: int = 20,
    base_url: Optional[str] = None,
    llm_base_url: str = "http://localhost:80/llm/qwen8b/v1",
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Extract queries and summarize user query patterns using LLM
    
    Args:
        api_key: API authorization key
        user_id: User identifier
        conversation_id: Conversation identifier
        limit: Maximum number of messages to retrieve
        base_url: Base URL for the API endpoint
        llm_base_url: Base URL for the local LLM API
        timeout: Request timeout in seconds (default: 30)
        
    Returns:
        Dictionary containing queries and summary
        
    Example:
        >>> result = summarize_user_queries(
        ...     api_key="your_api_key",
        ...     user_id="abc-123",
        ...     conversation_id="cd78daf6-f9e4-4463-9ff2-54257230a0ce"
        ... )
        >>> print(result['summary'])
        >>> print(f"Based on {len(result['queries'])} queries")
    """
    extractor = MessageExtractor(api_key, base_url, timeout)
    
    # Extract queries
    queries = extractor.extract_queries(user_id, conversation_id, limit)
    
    # Summarize with LLM
    summary = extractor.summarize_queries_with_llm(queries, llm_base_url)
    
    return {
        'queries': queries,
        'summary': summary,
        'query_count': len(queries)
    }


def update_user_profile_with_new_queries(
    api_key: str,
    user_id: str,
    conversation_id: str,
    db_config: Optional[Dict[str, Any]] = None,
    limit: int = 20,
    base_url: Optional[str] = None,
    llm_base_url: str = "http://localhost:80/llm/qwen8b/v1",
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Complete workflow: Get previous summary, extract queries, generate new summary, and update database
    This function is split into atomic operations for transaction safety
    
    Args:
        api_key: API authorization key
        user_id: User identifier
        conversation_id: Conversation identifier
        db_config: Database configuration dict (host, port, database, user, password).
                   If None, uses settings from app.core.config
        limit: Maximum number of messages to retrieve
        base_url: Base URL for the API endpoint
        llm_base_url: Base URL for the local LLM API
        timeout: Request timeout in seconds (default: 30)
        
    Returns:
        Dictionary containing operation results
        
    Example:
        >>> # Using default settings from config
        >>> result = update_user_profile_with_new_queries(
        ...     api_key="your_api_key",
        ...     user_id="abc-123",
        ...     conversation_id="cd78daf6-f9e4-4463-9ff2-54257230a0ce"
        ... )
        >>> 
        >>> # Or with custom db_config
        >>> result = update_user_profile_with_new_queries(
        ...     api_key="your_api_key",
        ...     user_id="abc-123",
        ...     conversation_id="cd78daf6-f9e4-4463-9ff2-54257230a0ce",
        ...     db_config={
        ...         'host': 'localhost',
        ...         'port': 5432,
        ...         'database': 'postgres',
        ...         'user': 'postgres',
        ...         'password': 'your_password'
        ...     }
        ... )
        >>> print(result['new_summary'])
        >>> print(f"Database updated: {result['db_updated']}")
    """
    # Initialize components (using settings from config by default)
    if db_config is None:
        db = UserProfileDB()  # Uses settings from app.core.config
    else:
        db = UserProfileDB(**db_config)
    extractor = MessageExtractor(api_key, base_url, timeout)
    
    result = {
        'user_id': user_id,
        'conversation_id': conversation_id,
        'queries': [],
        'query_count': 0,
        'previous_summary': None,
        'new_summary': None,
        'db_updated': False,
        'is_first_time': False
    }
    
    # Step 1: Get previous summary from database
    logger.info(f"Step 1: Getting previous summary for user {user_id}")
    previous_summary = db.get_latest_summary(user_id)
    result['previous_summary'] = previous_summary
    
    if previous_summary is None:
        result['is_first_time'] = True
        logger.info(f"First time user: {user_id}")
    
    # Step 2: Extract queries from conversation
    logger.info(f"Step 2: Extracting queries from conversation {conversation_id}")
    queries = extractor.extract_queries(user_id, conversation_id, limit)
    result['queries'] = queries
    result['query_count'] = len(queries)
    
    if not queries:
        logger.warning("No queries extracted, skipping summary generation")
        return result
    
    # Step 3: Generate new summary with LLM (incorporating previous summary if exists)
    logger.info(f"Step 3: Generating new summary (with previous: {previous_summary is not None})")
    new_summary = extractor.summarize_queries_with_llm(
        queries=queries,
        previous_summary=previous_summary,
        llm_base_url=llm_base_url
    )
    result['new_summary'] = new_summary
    
    # Step 4: Update database with new summary
    logger.info(f"Step 4: Updating database for user {user_id}")
    db_updated = db.upsert_latest_summary(user_id, new_summary)
    result['db_updated'] = db_updated
    
    if db_updated:
        logger.info(f"Successfully updated user profile for {user_id}")
    else:
        logger.error(f"Failed to update database for user {user_id}")
    
    return result


# if __name__ == "__main__":
#     # Example usage
#     print(f"Project root added to path: {sys.path[0]}\n")
#     logging.basicConfig(
#         level=logging.INFO,
#         format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
#     )
    
#     # Replace with actual values
#     API_KEY = "app-bBMVW3TWyJ94CobDSDuQpzTQ"
#     USER_ID = "abc-123"
#     CONVERSATION_ID = "17911dbd-0c7c-4b5d-b22c-9695c6c9ea1c"
    
#     print("\n" + "=" * 60)
#     print("Chat Message Archive - User Profile Update Demo")
#     print("=" * 60)
    
#     # Method 1: Simple query extraction and summary (no database)
#     # result = summarize_user_queries(
#     #     api_key=API_KEY,
#     #     user_id=USER_ID,
#     #     conversation_id=CONVERSATION_ID
#     # )
    
#     # Method 2: Complete workflow with database integration (using default settings)
#     result = update_user_profile_with_new_queries(
#         api_key=API_KEY,
#         user_id=USER_ID,
#         conversation_id=CONVERSATION_ID
#         # db_config is optional, defaults to settings from app.core.config
#     )
    
#     # Method 2b: With custom db_config (if you need to override defaults)
#     # result = update_user_profile_with_new_queries(
#     #     api_key=API_KEY,
#     #     user_id=USER_ID,
#     #     conversation_id=CONVERSATION_ID,
#     #     db_config={
#     #         'host': 'localhost',
#     #         'port': 5432,
#     #         'database': 'postgres',
#     #         'user': 'postgres',
#     #         'password': 'your_password'
#     #     }
#     # )
    
#     print(f"\n✓ 用户ID: {result['user_id']}")
#     print(f"✓ 成功提取 {result['query_count']} 条提问")
#     print(f"✓ 首次用户: {'是' if result['is_first_time'] else '否'}")
#     print(f"✓ 数据库更新: {'成功' if result['db_updated'] else '失败'}\n")
    
#     if result['previous_summary']:
#         print("=" * 60)
#         print("用户之前的聊天习惯总结：")
#         print("=" * 60)
#         print(result['previous_summary'])
    
#     print("\n提问列表：")
#     print("-" * 60)
#     for i, query in enumerate(result['queries'], 1):
#         print(f"{i}. {query}")
    
#     print("\n" + "=" * 60)
#     print("最新的用户聊天习惯总结（LLM生成）：")
#     print("=" * 60)
#     print(result['new_summary'])
#     print("=" * 60 + "\n")
    
#     # Method 3: Step-by-step atomic operations (for more control)
#     # Step 1: Initialize components
#     # db = UserProfileDB()  # Uses settings from app.core.config
#     # # Or with custom config:
#     # # db = UserProfileDB(host='localhost', port=5432, database='postgres', 
#     # #                    user='postgres', password='your_password')
#     # extractor = MessageExtractor(api_key=API_KEY)
    
#     # Step 2: Get previous summary
#     # previous_summary = db.get_latest_summary(USER_ID)
#     # print(f"Previous summary: {previous_summary}")
    
#     # Step 3: Extract queries
#     # queries = extractor.extract_queries(USER_ID, CONVERSATION_ID)
#     # print(f"Extracted {len(queries)} queries")
    
#     # Step 4: Generate new summary
#     # new_summary = extractor.summarize_queries_with_llm(
#     #     queries=queries,
#     #     previous_summary=previous_summary
#     # )
#     # print(f"New summary: {new_summary}")
    
#     # Step 5: Update database
#     # db.upsert_latest_summary(USER_ID, new_summary)
#     # print("Database updated")

