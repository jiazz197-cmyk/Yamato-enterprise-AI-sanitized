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
        model_name: str = "Qwen/Qwen3.5-35B-A3B-FP8",
        temperature: float = 0.3,
        max_tokens: int = 1024,
        dify_api_key: Optional[str] = None
    ):
        """
        Initialize the context compressor
        """
        self.base_url = base_url or settings.QWEN3_5_27B_API_URL
        self.model_name = model_name
        self.dify_api_key = dify_api_key or settings.CHAT_API_KEY
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        self.llm = ChatOpenAI(
            base_url=self.base_url,
            api_key="not-needed",
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        
        self.extractor = MessageExtractor(api_key=self.dify_api_key)
        
    def _fetch_and_split_dialogues(self, user_id: str, conversation_id: str, n: int = 5) -> Dict[str, List[str]]:
        """
        Fetch dialogues from Dify via variables endpoint and extract long_memory and recent_dialogs.
        """
        import requests
        import ast

        url = f"{self.extractor.base_url}/conversations/{conversation_id}/variables"
        params = {'user': user_id}
        
        try:
            logger.info(f"Fetching conversation variables from {url} with params: {params}")
            response = requests.get(
                url,
                headers=self.extractor.headers,
                params=params,
                timeout=self.extractor.timeout
            )
            response.raise_for_status()
            vars_data = response.json()
        except Exception as e:
            logger.error(f"Failed to fetch conversation variables: {str(e)}")
            return {"recent": [], "older": []}

        if not vars_data or 'data' not in vars_data:
            return {"recent": [], "older": []}
            
        long_memory_str = ""
        recent_dialogs_str = ""
        
        for item in vars_data['data']:
            if item.get('name') == 'long_memory':
                long_memory_str = item.get('value', '[]')
            elif item.get('name') == 'recent_dialogs':
                recent_dialogs_str = item.get('value', '[]')

        def safe_eval_list(val_str: str) -> List[str]:
            if not val_str or val_str == '[]':
                return []
            try:
                # Dify returns list as string representation like "['msg1', 'msg2']"
                return ast.literal_eval(val_str)
            except Exception as e:
                logger.warning(f"Failed to parse variable value '{val_str}': {str(e)}")
                return [val_str] if val_str else []

        older = safe_eval_list(long_memory_str)
        recent = safe_eval_list(recent_dialogs_str)
        
        return {
            "recent": recent,
            "older": older
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
            
        payload = {
            "system_prompt": context_data.get("system_prompt", "无"),
            "current_task": context_data.get("current_task", "无"),
            "recent_dialogues": join_dialogues(recent_dialogues),
            "older_dialogues": join_dialogues(older_dialogues),
            "user_preferences": context_data.get("user_preferences", "无"),
            "project_background": context_data.get("project_background", "无"),
            "confirmed_decisions": context_data.get("confirmed_decisions", "无")
        }

        try:
            logger.info(f"Starting context compression for user {user_id}...")
            raw_result = chain.invoke(payload)
        except Exception as e:
            # 兼容上下文接近上限时的 max_tokens 报错，自动收缩输出 token 后重试
            import re
            error_text = str(e)
            match = re.search(r"\((\d+)\s*>\s*(\d+)\s*-\s*(\d+)\)", error_text)
            if not match:
                logger.error(f"Error during context compression: {error_text}")
                raise e

            requested_max = int(match.group(1))
            max_context = int(match.group(2))
            input_tokens = int(match.group(3))
            available = max_context - input_tokens - 64  # 预留安全余量，防止边界抖动
            retry_max_tokens = min(requested_max, self.max_tokens, max(64, available))

            if retry_max_tokens <= 0:
                logger.error(f"Error during context compression: {error_text}")
                raise e

            logger.warning(
                "Context close to model limit, retrying with reduced max_tokens: "
                f"requested={requested_max}, available={max_context - input_tokens}, retry={retry_max_tokens}"
            )

            retry_llm = ChatOpenAI(
                base_url=self.base_url,
                api_key="not-needed",
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=retry_max_tokens
            )
            retry_chain = prompt | retry_llm | StrOutputParser()
            raw_result = retry_chain.invoke(payload)

        # 后处理：移除可能出现的 <think> 标签内容
        import re
        processed_result = re.sub(r'<think>.*?</think>', '', raw_result, flags=re.DOTALL | re.IGNORECASE).strip()
        # 如果模型没有输出 </think> 导致匹配失败，尝试简单截断
        if '<think>' in processed_result.lower():
            # 大小写不敏感地截断
            processed_result = re.split(r'<think>', processed_result, flags=re.IGNORECASE)[0].strip()

        logger.info(f"[Debug] Raw Compression Result length: {len(raw_result)}")
        logger.info(f"[Debug] Raw Compression Result snippet: {raw_result[:200]} ... {raw_result[-200:] if len(raw_result) > 400 else ''}")
        logger.info(f"[Debug] Processed Compression Result length: {len(processed_result)}")
        logger.info(f"[Debug] Processed Compression Result snippet: {processed_result[:200]}")
        
        logger.info("Context compression completed successfully.")
        return processed_result

def compress_context(context_data: Dict[str, Any]) -> str:
    """
    Convenience function to compress context using default settings.
    """
    compressor = ContextCompressor()
    return compressor.compress(context_data)
