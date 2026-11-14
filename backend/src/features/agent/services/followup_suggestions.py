"""追问建议 mixin：每轮 done 后的后续问题建议生成（独立 LLM 调用，纯搬移自 chat_service）。

依赖主类属性：self.db/self.model_config_service；logger 本模块自建。
"""
import json

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.agent.exceptions import (
    AgentError,
    SessionNotFoundError,
)
from novamind.shared.prompts.prompt_manager import PromptManager

logger = get_logger(__name__)


class FollowupSuggestionsMixin:
    """追问建议 mixin：每轮 done 后的后续问题建议生成（独立 LLM 调用，纯搬移自 chat_service）。"""

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def generate_followup_suggestions(
        self,
        user_id: int,
        session_id: str,
        llm_model: str | None = None,
    ) -> list[str]:
        """基于会话最近消息生成追问建议（每轮回答后调用，前端 pills 展示）。

        Args:
            user_id: 当前用户 ID（会话归属校验）。
            session_id: 会话 UUID。
            llm_model: 覆盖 Agent 配置的模型名；缺省跟随 Agent 配置或用户默认。

        Returns:
            最多 3 条追问文本；会话无 user/assistant 内容或模型输出不可解析时
            返回空数组——追问是增强能力，空态由前端静默处理不提示错误。

        Raises:
            SessionNotFoundError: 会话不存在或不属于当前用户（与消息读取同防线、同 404 口径）。
        """
        conv = await self.session_repo.get_by_session_id(session_id)
        if conv is None or conv.user_id != user_id:
            raise SessionNotFoundError(session_id)
        if conv.message_count <= 0:
            return []

        # 尾部窗口先放宽再过滤：tool/compaction 等过程行穿插时会挤占固定窗口，
        # 只留 user/assistant 对话文本（过程行无追问价值）。
        # list_recent_by_conversation 返回时间升序，直接取尾部窗口即「最新 N 条」
        recent = await self.msg_repo.list_recent_by_conversation(
            conv.id, limit=30
        )
        lines = [
            f"{'User' if m.role == 'user' else 'Assistant'}: "
            f"{(m.content or '')[: self.FOLLOWUP_MESSAGE_CHARS]}"
            for m in recent
            if m.role in ("user", "assistant") and (m.content or "").strip()
        ]
        if not lines:
            return []
        conversation_text = "\n".join(lines[-self.FOLLOWUP_CONTEXT_MESSAGES :])

        agent = await self.agent_service.agent_repo.get_by_id(conv.agent_id)
        if agent is None:
            raise AgentError("会话关联的智能体不存在")
        model = await self._resolve_model(user_id, agent, llm_model)
        # 客户端获取与 _build_context 同口径：优先 LLM 类型，fallback VLM
        try:
            llm_client = await self.model_config_service.get_llm_client_by_model(
                user_id, model
            )
        except Exception:
            llm_client = await self.model_config_service.get_vlm_client_by_model(
                user_id, model
            )

        prompt = PromptManager.format_prompt(
            "agent_followup_suggestions", conversation_text=conversation_text
        )
        # get_llm_client_by_model 返回 BaseLLM（无 AgentLLM.generate 包装层），
        # 直接用其非流式纯文本接口；工具传 None 即纯生成
        response = await llm_client.generate_with_tools(
            prompt=[{"role": "user", "content": prompt}],
            tools=None,
            max_tokens=300,
            temperature=0.8,
            enable_thinking=False,
        )
        return self._parse_followup_suggestions(
            response.content, self.FOLLOWUP_MAX_ITEMS
        )

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    @staticmethod
    def _parse_followup_suggestions(content: str, max_items: int) -> list[str]:
        """从模型输出解析追问数组：截取 JSON 数组段容错，不可解析返回空并告警。"""
        text = (content or "").strip()
        # 剥围栏与前后杂质：取首个 '[' 到末个 ']' 之间的段
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end <= start:
            logger.warning("追问建议输出不含 JSON 数组", output=text[:200])
            return []
        try:
            items = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("追问建议 JSON 解析失败", output=text[start : end + 1][:200])
            return []
        cleaned: list[str] = []
        for item in items if isinstance(items, list) else []:
            s = str(item).strip()
            if s and len(s) <= 100:
                cleaned.append(s)
            if len(cleaned) >= max_items:
                break
        return cleaned

