"""
Context Compression Workflow
Uses local vLLM (Qwen3:8b) via LangChain to compress context.
Fetches dialogue history from Dify.
"""
import logging
from typing import Dict, Any, List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.core.config import settings
from app.integrations.Chat_message_archive.message_extractor import MessageExtractor

logger = logging.getLogger(__name__)

class ContextCompressor:
    """
    Compresses chat context into a structured, concise format using LLM.
    """
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        model_name: str = "Qwen/Qwen3-8B-FP8",
        temperature: float = 0.3,
        max_tokens: int = 1024,
        dify_api_key: Optional[str] = None
    ):
        """
        Initialize the context compressor
        """
        self.base_url = base_url or settings.QWEN3_8B_API_URL
        self.model_name = model_name
        self.dify_api_key = dify_api_key or settings.CHAT_API_KEY
        
        self.llm = ChatOpenAI(
            base_url=self.base_url,
            api_key="not-needed",
            model=self.model_name,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        self.extractor = MessageExtractor(api_key=self.dify_api_key)
        
    def _fetch_and_split_dialogues(self, user_id: str, conversation_id: str, n: int = 5) -> Dict[str, List[str]]:
        """
        Fetch dialogues from Dify and split into recent N and older ones.
        """
        # Fetch more to have enough for "older"
        messages_data = self.extractor.get_messages(user_id=user_id, conversation_id=conversation_id, limit=50)
        if not messages_data or 'data' not in messages_data:
            return {"recent": [], "older": []}
            
        data = messages_data['data']
        # Dify usually returns messages in reverse chronological order (newest first)
        # But we need to check or ensure the order. 
        # For compression, we extract query/answer pairs.
        
        formatted_dialogues = []
        for msg in data:
            query = msg.get('query', '')
            answer = msg.get('answer', '')
            if query:
                formatted_dialogues.append(f"User: {query}")
            if answer:
                formatted_dialogues.append(f"AI: {answer}")
        
        # Split: recent N turns (1 turn = 1 user + 1 ai) -> approx 2*n messages
        recent_count = 2 * n
        recent = formatted_dialogues[:recent_count]
        older = formatted_dialogues[recent_count:]
        
        return {
            "recent": recent[::-1], # Back to chronological for prompt
            "older": older[::-1]
        }

    def compress(self, context_data: Dict[str, Any]) -> str:
        """
        Compress the provided context data into a summary.
        
        Args:
            context_data: Dictionary containing:
                - user_id: str
                - conversation_id: str
                - system_prompt: str
                - current_task: str
                - n_recent: int (default 5)
                - user_preferences: str
                - project_background: str
                - confirmed_decisions: str
                
        Returns:
            Compressed string representation (<= 200 words)
        """
        user_id = context_data.get("user_id")
        conversation_id = context_data.get("conversation_id")
        n_recent = context_data.get("n_recent", 5)
        
        if user_id and conversation_id:
            dialogues = self._fetch_and_split_dialogues(user_id, conversation_id, n_recent)
            recent_dialogues = dialogues["recent"]
            older_dialogues = dialogues["older"]
        else:
            recent_dialogues = context_data.get("recent_dialogues", [])
            older_dialogues = context_data.get("older_dialogues", [])

        system_template = """你是一个专业的上下文压缩助手。你的任务是将冗长的对话和背景信息压缩成极其精简且高密度的格式。

**必须严格遵守以下规则：**
1. **必须**严格按照以下三部分进行输出，且每部分必须包含标题（使用 ** 加粗）：
   - **工作上下文（working context）**：当前的系统提示关键点、当前任务、以及最近N轮对话核心。
   - **会话摘要（session summary）**：把较早的对话压缩成“到目前为止发生了什么”。
   - **长期记忆（durable memory）**：提炼用户偏好、长期约束、术语表、项目背景、已确认决策。
2. **总字数控制在300字左右。** 优先保证信息完整性，绝对不能在话说到一半时截断。
3. 使用极其简练的短句，保留关键实体和动作。
4. 确保最终输出包含完整的三个部分，并在完成所有总结后结束。
5. 不要加入任何多余的客套话或解释性文本。"""

        human_template = """请按照要求压缩以下信息：

【当前系统提示】：{system_prompt}
【当前任务】：{current_task}
【最近对话】：
{recent_dialogues}

【较早对话】：
{older_dialogues}

【用户偏好与长期约束】：{user_preferences}
【项目背景与术语】：{project_background}
【已确认的决策】：{confirmed_decisions}"""

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_template),
            ("human", human_template)
        ])
        
        chain = prompt | self.llm | StrOutputParser()
        
        def join_dialogues(dialogues: Any) -> str:
            if not dialogues:
                return "无"
            if isinstance(dialogues, list):
                return "\n".join(f"- {d}" for d in dialogues)
            return str(dialogues)
            
        try:
            logger.info(f"Starting context compression for user {user_id}...")
            raw_result = chain.invoke({
                "system_prompt": context_data.get("system_prompt", "无"),
                "current_task": context_data.get("current_task", "无"),
                "recent_dialogues": join_dialogues(recent_dialogues),
                "older_dialogues": join_dialogues(older_dialogues),
                "user_preferences": context_data.get("user_preferences", "无"),
                "project_background": context_data.get("project_background", "无"),
                "confirmed_decisions": context_data.get("confirmed_decisions", "无")
            })
            
            # 后处理：移除可能出现的 <think> 标签内容
            import re
            processed_result = re.sub(r'<think>.*?</think>', '', raw_result, flags=re.DOTALL).strip()
            # 如果模型没有输出 </think> 导致匹配失败，尝试简单截断
            if '<think>' in processed_result:
                processed_result = processed_result.split('<think>')[-1].split('</think>')[-1].strip()
            
            logger.info("Context compression completed successfully.")
            return processed_result
        except Exception as e:
            logger.error(f"Error during context compression: {str(e)}")
            raise e

def compress_context(context_data: Dict[str, Any]) -> str:
    """
    Convenience function to compress context using default settings.
    """
    compressor = ContextCompressor()
    return compressor.compress(context_data)
