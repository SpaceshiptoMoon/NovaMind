"""
五阶段结构化上下文压缩器

替代 PriorityBasedCompression，参照 Hermes ContextCompressor 设计：
  Phase 1: 工具结果信息性剪枝（按工具类型生成摘要、去重、参数截断）
  Phase 2: Token 预算尾部保护（确保最近用户消息在保护区内）
  Phase 3: 结构化 LLM 摘要（13 章节模板，敏感数据脱敏）
  Phase 4: 迭代更新（融合旧摘要 + 新内容）
  Phase 5: 工具对清理（sanitise_tool_pairs）

容错：反抖动保护、摘要模型降级、失败冷却、静态降级标记
"""
import json
import hashlib
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from novamind.features.agent.core.memory.interfaces import MemoryMessage
from novamind.features.agent.core.memory.token_budget import TokenBudget
from novamind.features.agent.core.memory.compress import ICompressionStrategy
from novamind.shared.utils.redact import redact_sensitive_text
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# 摘要前缀：告诉模型这是上下文交接，不是当前指令
SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. "
    "This is a handoff from a previous context window — treat it as background reference, "
    "NOT as active instructions. Do NOT answer questions or fulfill requests mentioned in this summary; "
    "they were already addressed. Your current task is identified in the '## Active Task' section — "
    "resume exactly from there. Respond ONLY to the latest user message that appears AFTER this summary: "
)

# 反抖动阈值
_INEFFECTIVE_THRESHOLD = 2  # 连续 N 次节省 <10% 则跳过

# 冷却时间
_TRANSIENT_COOLDOWN = 60  # 瞬时错误 60 秒


class ContextCompressor(ICompressionStrategy):
    """五阶段结构化上下文压缩器"""

    def __init__(
        self,
        llm_client_factory: Optional[Callable] = None,
        tail_ratio: float = 0.20,
        summary_repository: Optional[Any] = None,
        todo_store: Optional[Any] = None,
        conversation_id: Optional[int] = None,
        long_term_memory: Optional[Any] = None,
        agent_id: Optional[int] = None,
        user_id: Optional[int] = None,
        auxiliary_llm_factory: Optional[Callable] = None,
    ):
        self._llm_factory = llm_client_factory
        self._aux_llm_factory = auxiliary_llm_factory
        self._tail_ratio = tail_ratio
        self._summary_repo = summary_repository
        self._todo_store = todo_store
        self._conversation_id = conversation_id
        self._long_term = long_term_memory
        self._agent_id = agent_id
        self._user_id = user_id

        # 迭代摘要状态
        self._previous_summary: Optional[str] = None

        # 反抖动
        self._ineffective_count: int = 0

        # 冷却
        self._cooldown_until: float = 0.0
        self._last_error: Optional[str] = None

    async def compress(
        self,
        messages: List[MemoryMessage],
        available_tokens: int,
        token_budget: TokenBudget,
        conversation_id: Optional[int] = None,
    ) -> Tuple[List[MemoryMessage], bool, float]:
        """执行五阶段压缩"""
        if len(messages) <= 4:
            return messages, False, 1.0

        original_tokens = token_budget.count_messages_tokens(messages)
        if original_tokens <= available_tokens:
            return messages, False, 1.0

        # 反抖动检查
        if self._ineffective_count >= _INEFFECTIVE_THRESHOLD:
            logger.warning("压缩已跳过 — 最近 %d 次压缩各节省 <10%%", _INEFFECTIVE_THRESHOLD)
            return messages, False, 1.0

        working = list(messages)

        # Phase 1: 工具结果信息性剪枝
        working, pruned = self._prune_tool_results(working)
        if pruned:
            logger.debug("Phase 1: 剪枝了 %d 条工具结果", pruned)

        # Phase 2: Token 预算尾部保护 + 确定压缩边界
        tail_budget = int(available_tokens * self._tail_ratio)
        compress_end = self._find_tail_cut(working, tail_budget, token_budget)
        if compress_end <= 1:
            # 所有内容都在保护区，只做 Phase 5
            working = self._sanitise_tool_pairs(working)
            return working, False, 1.0

        turns_to_compress = working[:compress_end]
        tail = working[compress_end:]

        # 记忆提取：在压缩丢弃前从旧轮次中提取长期记忆
        await self._extract_memories(turns_to_compress, conversation_id or self._conversation_id)

        # Phase 3/4: 结构化 LLM 摘要
        summary = await self._generate_summary(turns_to_compress, token_budget, conversation_id)
        summary_content = summary or self._static_fallback(len(turns_to_compress))

        # Phase 5: 工具对清理
        # 智能选择摘要角色：避免和 head 末尾、tail 开头连续同角色
        head_last_role = turns_to_compress[-1].role if turns_to_compress else None
        tail_first_role = tail[0].role if tail else None
        summary_role = self._pick_summary_role(head_last_role, tail_first_role)

        if summary_role:
            # 正常情况：插入一条独立消息
            summary_msg = MemoryMessage(role=summary_role, content=summary_content)
            compressed = [summary_msg] + tail
        else:
            # 两种角色都冲突：合并到第一条 tail 消息
            separator = "\n\n--- 以上为上下文摘要，请回应下方消息 ---\n\n"
            merged_content = summary_content + separator + (tail[0].content or "")
            tail[0] = MemoryMessage(
                role=tail[0].role,
                content=merged_content,
                tool_calls=tail[0].tool_calls,
                tool_call_id=tail[0].tool_call_id,
                tool_name=tail[0].tool_name,
                token_count=tail[0].token_count,
                metadata=tail[0].metadata,
            )
            compressed = list(tail)

        compressed = self._sanitise_tool_pairs_mem(compressed)

        # TodoStore 注入：压缩后重新注入 pending/in_progress 任务
        if self._todo_store and self._conversation_id:
            todo_text = self._todo_store.format_for_injection(self._conversation_id)
            if todo_text:
                compressed.append(MemoryMessage(
                    role="user",
                    content=todo_text,
                ))
                logger.debug("TodoStore 任务已注入压缩结果")

        # 统计
        new_tokens = token_budget.count_messages_tokens(compressed)
        ratio = new_tokens / original_tokens if original_tokens > 0 else 1.0
        savings = 1.0 - ratio

        # 持久化摘要到 agent_context_summaries
        if summary and conversation_id and self._summary_repo:
            try:
                summary_token_count = token_budget.count_text_tokens(summary)
                await self._summary_repo.create(
                    conversation_id=conversation_id,
                    summary_text=summary,
                    compressed_count=len(turns_to_compress),
                    compression_ratio=ratio,
                    token_count=summary_token_count,
                )
            except Exception as e:
                logger.warning("摘要持久化失败", error=str(e))

        # 反抖动追踪
        if savings < 0.10:
            self._ineffective_count += 1
        else:
            self._ineffective_count = 0

        logger.info(
            "五阶段压缩完成",
            original=len(messages),
            compressed=len(compressed),
            ratio=round(ratio, 2),
            phase1_pruned=pruned,
        )
        return compressed, True, ratio

    # ==================== Phase 1: 工具结果信息性剪枝 ====================

    def _prune_tool_results(
        self, messages: List[MemoryMessage]
    ) -> Tuple[List[MemoryMessage], int]:
        """剪枝旧工具结果：信息性摘要 + 去重 + 参数截断"""
        if not messages:
            return messages, 0

        result = [m if not isinstance(m, MemoryMessage) else m for m in messages]
        pruned = 0

        # 保护尾部 30% 的消息
        protect_count = max(3, len(result) // 3)
        prune_boundary = max(0, len(result) - protect_count)

        # Pass 1: 去重相同工具输出
        content_hashes: Dict[str, int] = {}
        for i in range(len(result) - 1, -1, -1):
            msg = result[i]
            if msg.role != "tool" or not msg.content or len(msg.content) < 200:
                continue
            h = hashlib.md5(msg.content.encode("utf-8", errors="replace")).hexdigest()[:12]
            if h in content_hashes:
                result[i] = MemoryMessage(
                    role=msg.role,
                    content="[重复工具输出 — 与更新的调用内容相同]",
                    tool_call_id=msg.tool_call_id,
                    tool_name=msg.tool_name,
                )
                pruned += 1
            else:
                content_hashes[h] = i

        # Pass 2: 信息性摘要替换
        for i in range(prune_boundary):
            msg = result[i]
            if msg.role != "tool" or not msg.content:
                continue
            if len(msg.content) <= 200:
                continue
            if msg.content.startswith("[重复工具输出"):
                continue
            summary = self._summarize_tool_result(msg.tool_name, msg.content)
            result[i] = MemoryMessage(
                role=msg.role,
                content=summary,
                tool_call_id=msg.tool_call_id,
                tool_name=msg.tool_name,
            )
            pruned += 1

        # Pass 3: 截断 assistant 消息中的工具调用参数
        for i in range(prune_boundary):
            msg = result[i]
            if msg.role != "assistant" or not msg.tool_calls:
                continue
            new_tcs = []
            modified = False
            for tc in msg.tool_calls:
                if isinstance(tc, dict):
                    args = tc.get("function", {}).get("arguments", "")
                    if len(args) > 500:
                        args = self._truncate_tool_args(args)
                        tc = {**tc, "function": {**tc["function"], "arguments": args}}
                        modified = True
                new_tcs.append(tc)
            if modified:
                result[i] = MemoryMessage(
                    role=msg.role,
                    content=msg.content,
                    tool_calls=new_tcs,
                    tool_call_id=msg.tool_call_id,
                    tool_name=msg.tool_name,
                )

        return result, pruned

    @staticmethod
    def _summarize_tool_result(tool_name: Optional[str], content: str) -> str:
        """为工具结果生成语义化一行摘要"""
        name = tool_name or "unknown"
        content_len = len(content)
        lines = content.count("\n") + 1 if content.strip() else 0

        # 尝试 JSON 解析提取结构化信息
        parsed = None
        try:
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                parsed = None
        except (json.JSONDecodeError, TypeError):
            pass

        if name in ("knowledge_search", "knowledge-base"):
            query = (parsed or {}).get("query", "")
            results = (parsed or {}).get("results", [])
            parts = [f"[{name}]"]
            if query:
                parts.append(f'query="{query[:100]}"')
            if isinstance(results, list):
                parts.append(f"{len(results)} results")
            parts.append(f"({content_len:,} chars)")
            return " ".join(parts)

        if name in ("web_search",):
            query = (parsed or {}).get("query", "")
            results = (parsed or {}).get("results", [])
            parts = [f"[{name}]"]
            if query:
                parts.append(f'query="{query[:100]}"')
            if isinstance(results, list):
                parts.append(f"{len(results)} results")
            parts.append(f"({content_len:,} chars)")
            return " ".join(parts)

        if name in ("code_execution",):
            exit_code = (parsed or {}).get("exit_code") if parsed else None
            output = (parsed or {}).get("output", "") if parsed else content
            preview = (output or content)[:80].replace("\n", " ")
            parts = [f"[{name}]"]
            if exit_code is not None:
                parts.append(f"exit={exit_code}")
            if len(content) > 80:
                preview += "..."
            parts.append(f"`{preview}`")
            parts.append(f"({lines} lines)")
            return " ".join(parts)

        if name.startswith("mcp__"):
            preview = content[:80].replace("\n", " ")
            suffix = "..." if len(content) > 80 else ""
            return f"[{name}] {preview}{suffix} ({content_len:,} chars)"

        return f"[{name}] ({content_len:,} chars, {lines} lines)"

    @staticmethod
    def _truncate_tool_args(args: str, head_chars: int = 200) -> str:
        """截断工具调用参数 JSON，保持 JSON 有效性"""
        try:
            parsed = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return args[:head_chars] + "...[truncated]"

        def _shrink(obj: Any) -> Any:
            if isinstance(obj, str):
                return obj[:head_chars] + "...[truncated]" if len(obj) > head_chars else obj
            if isinstance(obj, dict):
                return {k: _shrink(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_shrink(v) for v in obj]
            return obj

        return json.dumps(_shrink(parsed), ensure_ascii=False)

    # ==================== Phase 2: Token 预算尾部保护 ====================

    def _find_tail_cut(
        self, messages: List[MemoryMessage], tail_token_budget: int,
        token_budget: Optional[TokenBudget] = None,
    ) -> int:
        """从末尾向前累加 token，找到压缩边界（使用精确 token 计数）"""
        n = len(messages)
        min_tail = min(3, n - 1)
        soft_ceiling = int(tail_token_budget * 1.5)
        accumulated = 0
        cut_idx = n

        for i in range(n - 1, 0, -1):
            msg = messages[i]
            if token_budget:
                msg_tokens = 4  # role overhead
                if msg.content:
                    msg_tokens += token_budget.count_text_tokens(msg.content)
                if msg.tool_calls:
                    msg_tokens += token_budget.count_text_tokens(
                        json.dumps(msg.tool_calls, ensure_ascii=False)
                    )
                if msg.tool_call_id:
                    msg_tokens += 6
                if msg.tool_name:
                    msg_tokens += 3
            else:
                msg_tokens = (len(str(msg.content or "")) // 4) + 10
            if accumulated + msg_tokens > soft_ceiling and (n - i) >= min_tail:
                break
            accumulated += msg_tokens
            cut_idx = i

        # 确保至少 min_tail 条消息在保护区
        fallback_cut = n - min_tail
        if cut_idx > fallback_cut:
            cut_idx = fallback_cut

        # 确保最近 user 消息在保护区
        last_user = -1
        for i in range(n - 1, 0, -1):
            if messages[i].role == "user":
                last_user = i
                break
        if last_user >= 0 and last_user < cut_idx:
            cut_idx = max(last_user, 1)

        # 边界对齐：不拆散 tool_call/result 组
        cut_idx = self._align_boundary(messages, cut_idx)

        return cut_idx

    def _align_boundary(self, messages: List[MemoryMessage], cut_idx: int) -> int:
        """将压缩边界对齐到 tool 组边界，避免拆散 tool_call/result 配对。

        向前扫描：如果 cut_idx 落在一个 tool 组内部，向前推到该组的起始位置，
        将整组纳入 head（被压缩区域）。
        """
        n = len(messages)
        if cut_idx <= 1 or cut_idx >= n:
            return cut_idx

        # 从 cut_idx 向前找，看是否在 tool 组内部
        # tool 组结构: assistant(tool_calls) → tool(result)* → ... → assistant(tool_calls)
        # 情况 1: cut_idx 处是 tool 消息，说明切在了 assistant(tool_calls) 之后
        #         需要向前推过这个 assistant 消息
        # 情况 2: cut_idx 处是 assistant(tool_calls)，但前方有未配对的 tool(result)
        #         说明前面有 tool 消息属于这个 assistant，需要一起推到 head

        # 先向前跳过连续的 tool 消息（它们属于 cut_idx 前面的 assistant）
        aligned = cut_idx
        while aligned > 1 and messages[aligned - 1].role == "tool":
            aligned -= 1

        # 现在 aligned-1 要么是发起这些 tool 的 assistant，要么不是
        # 检查前一条是否是带 tool_calls 的 assistant
        if aligned > 1 and messages[aligned - 1].role == "assistant" and messages[aligned - 1].tool_calls:
            # 把这个 assistant 也纳入 head（被压缩）
            aligned -= 1

        if aligned < cut_idx:
            logger.debug(
                "边界对齐: %d → %d (整组 tool_call/result 纳入 head)",
                cut_idx, aligned,
            )

        return max(aligned, 1)

    @staticmethod
    def _pick_summary_role(
        head_last_role: Optional[str], tail_first_role: Optional[str]
    ) -> Optional[str]:
        """选择摘要消息角色，避免和前后消息连续同角色。

        Returns:
            "user" / "assistant" / None（None 表示两种都冲突，需合并到 tail）
        """
        # 不使用 "system"：head 末尾可能是上一次压缩的 system 摘要
        # 优先选 "user"，其次选 "assistant"
        for candidate in ("user", "assistant"):
            if candidate != head_last_role and candidate != tail_first_role:
                return candidate
        return None

    # ==================== Phase 3/4: 结构化 LLM 摘要 ====================

    async def _generate_summary(
        self, turns: List[MemoryMessage], token_budget: TokenBudget,
        conversation_id: Optional[int] = None,
    ) -> Optional[str]:
        """生成结构化摘要（首次或迭代更新）"""
        if not self._llm_factory:
            return None

        now = time.monotonic()
        if now < self._cooldown_until:
            logger.debug("摘要生成在冷却中")
            return None

        # 序列化 + 脱敏
        content = self._serialize_turns(turns)
        content = redact_sensitive_text(content)

        # 加载旧摘要：优先内存缓存，其次从 DB 加载
        old_summary = self._previous_summary
        if not old_summary and self._summary_repo and conversation_id:
            try:
                latest = await self._summary_repo.get_latest(conversation_id)
                if latest:
                    old_summary = latest.summary_text
                    logger.debug("从 DB 加载旧摘要用于增量融合", conversation_id=conversation_id)
            except Exception as e:
                logger.warning("加载旧摘要失败", error=str(e))

        if old_summary:
            prompt = self._build_merge_prompt(old_summary, content)
        else:
            prompt = self._build_summary_prompt(content)

        try:
            # 优先使用廉价辅助模型，降级到主模型
            factory = self._aux_llm_factory or self._llm_factory
            llm = await factory() if factory else None
            if llm is None:
                return None
            summary = await llm.generate_text(
                prompt=prompt,
                max_tokens=4096,
                temperature=0.3,
            )
            summary = summary.strip()
            summary = redact_sensitive_text(summary)
            summary = f"{SUMMARY_PREFIX}\n{summary}"

            # 存储用于下次迭代
            self._previous_summary = summary
            self._cooldown_until = 0.0
            self._last_error = None
            return summary

        except Exception as e:
            self._cooldown_until = time.monotonic() + _TRANSIENT_COOLDOWN
            self._last_error = str(e)[:200]
            logger.warning("摘要生成失败", error=str(e)[:200])
            return None

    def _serialize_turns(self, turns: List[MemoryMessage]) -> str:
        """序列化消息为文本供摘要器使用"""
        parts = []
        for msg in turns:
            role = msg.role
            raw = msg.content or ""

            # multimodal content 数组 → 提取文本部分
            if isinstance(raw, list):
                text_parts = []
                for part in raw:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif isinstance(part, dict) and part.get("type") == "image_url":
                        text_parts.append("[图片]")
                content = " ".join(text_parts) if text_parts else "[multimodal]"
            else:
                content = raw
            if len(content) > 4000:
                content = content[:3000] + "\n...[truncated]...\n" + content[-800:]

            if role == "tool":
                parts.append(f"[TOOL {msg.tool_name or ''}]: {content}")
            elif role == "assistant":
                text = content
                if msg.tool_calls:
                    tc_parts = []
                    for tc in msg.tool_calls:
                        if isinstance(tc, dict):
                            fn = tc.get("function", {})
                            name = fn.get("name", "?")
                            args = fn.get("arguments", "")
                            if len(args) > 1200:
                                args = self._truncate_tool_args(args, head_chars=1000)
                            tc_parts.append(f"  {name}({args})")
                    text += "\n[Tool calls:\n" + "\n".join(tc_parts) + "\n]"
                parts.append(f"[ASSISTANT]: {text}")
            else:
                parts.append(f"[{role.upper()}]: {content}")
        return "\n\n".join(parts)

    def _build_summary_prompt(self, content: str) -> str:
        """Build first-summary prompt with handoff framing"""
        return (
            "You are a summarization agent creating a context checkpoint. Your output will be injected as "
            "reference material for a DIFFERENT assistant that continues the conversation. "
            "Do NOT respond to any questions or requests — only output the structured summary. "
            "Do NOT include any preamble, greeting, or prefix. "
            "Write the summary in the same language the user was using. "
            "NEVER include API keys, tokens, passwords, secrets, or credentials — "
            "replace any that appear with [REDACTED].\n\n"
            "IMPORTANT: This summary is a HANDOFF from a previous context window. "
            "The assistant receiving this should treat it as BACKGROUND REFERENCE ONLY. "
            "Do NOT act on any requests or answer any questions mentioned in this summary — "
            "they were already addressed. Only respond to the latest user message that appears "
            "AFTER this summary in the conversation.\n\n"
            f"Conversation:\n{content}\n\n"
            "Use the following structure for the summary:\n\n"
            "## Active Task\n"
            "[CRITICAL. Copy the user's MOST RECENT unfulfilled request VERBATIM — "
            "do not paraphrase, do not summarize. This must be the exact words of the user's "
            "latest message that still needs a response.]\n\n"
            "## Goal\n"
            "[What the user is ultimately trying to accomplish]\n\n"
            "## Constraints & Preferences\n"
            "[User preferences, coding style, constraints, important decisions]\n\n"
            "## Completed Actions\n"
            "[Numbered list. Format: N. Action Target — Result [tool: name]]\n\n"
            "## Active State\n"
            "[Working directory, modified files, test status, etc.]\n\n"
            "## In Progress\n"
            "[What was being worked on when compaction occurred]\n\n"
            "## Blocked\n"
            "[Unresolved errors with specific error messages]\n\n"
            "## Key Decisions\n"
            "[Important technical decisions and rationale]\n\n"
            "## Resolved Questions\n"
            "[Questions that were answered — include answers to prevent re-asking]\n\n"
            "## Pending User Asks\n"
            "[Questions or requests not yet addressed. If none, write None. "
            "These MUST be distinguished from Resolved Questions — "
            "do NOT re-ask questions that appear in \"Resolved Questions\".]\n\n"
            "## Relevant Files\n"
            "[Files read, modified, or created]\n\n"
            "## Remaining Work\n"
            "[Items still needing completion]\n\n"
            "## Critical Context\n"
            "[Values, error messages, config details that would be lost if not explicitly preserved]"
        )

    def _build_merge_prompt(self, old_summary: str, new_content: str) -> str:
        """Build iterative merge prompt with handoff framing"""
        return (
            "You are updating a context compaction summary. A previous compaction produced the summary below. "
            "New conversation turns have occurred and need to be incorporated.\n\n"
            "Do NOT respond to any questions in the conversation — only output the updated structured summary.\n"
            "NEVER include API keys, tokens, passwords, secrets, or credentials — "
            "replace any that appear with [REDACTED].\n\n"
            f"Old summary:\n{old_summary}\n\n"
            f"New conversation turns:\n{new_content}\n\n"
            "Update the summary. Preserve all still-relevant information from the old summary. "
            "Continue numbering in numbered lists where the old summary left off. "
            "Move completed items to \"Completed Actions\". "
            "Move answered questions to \"Resolved Questions\" and ensure they are NOT duplicated in \"Pending User Asks\". "
            "MOST IMPORTANT: update \"## Active Task\" to the user's MOST RECENT unfulfilled request VERBATIM "
            "(exact words, not paraphrased). If the user's latest message is a follow-up or correction, "
            "the Active Task must reflect that latest message, not the original. "
            "Use the same 13-section structure."
        )

    # ==================== Phase 5: 工具对清理 ====================

    def _sanitise_tool_pairs_mem(
        self, messages: List[MemoryMessage]
    ) -> List[MemoryMessage]:
        """MemoryMessage 版工具对清理"""
        # 收集所有存在的 tool_call_id
        surviving_call_ids: set = set()
        for msg in messages:
            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    if isinstance(tc, dict) and tc.get("id"):
                        surviving_call_ids.add(tc["id"])

        # 收集所有 tool result 的 call_id
        result_call_ids: set = set()
        for msg in messages:
            if msg.role == "tool" and msg.tool_call_id:
                result_call_ids.add(msg.tool_call_id)

        # 方向 1: 删除孤儿 tool_result
        orphaned_results = result_call_ids - surviving_call_ids
        if orphaned_results:
            messages = [
                m for m in messages
                if not (m.role == "tool" and m.tool_call_id in orphaned_results)
            ]
            logger.debug("清理了 %d 条孤儿 tool_result", len(orphaned_results))

        # 方向 2: 为孤儿 tool_call 插入 stub result
        missing_results = surviving_call_ids - result_call_ids
        if missing_results:
            patched: List[MemoryMessage] = []
            for msg in messages:
                patched.append(msg)
                if msg.role == "assistant" and msg.tool_calls:
                    for tc in msg.tool_calls:
                        if isinstance(tc, dict) and tc.get("id") in missing_results:
                            patched.append(MemoryMessage(
                                role="tool",
                                content="[来自之前对话的结果 — 见上方上下文摘要]",
                                tool_call_id=tc["id"],
                            ))
            messages = patched
            logger.debug("插入了 %d 条 stub tool_result", len(missing_results))

        return messages

    def _sanitise_tool_pairs(
        self, messages: List[MemoryMessage]
    ) -> List[MemoryMessage]:
        """公开的工具对清理（无摘要时使用）"""
        return self._sanitise_tool_pairs_mem(messages)

    # ==================== 静态降级 ====================

    async def _extract_memories(
        self,
        turns: List[MemoryMessage],
        conversation_id: Optional[int],
    ) -> None:
        """从即将被压缩丢弃的轮次中提取长期记忆（write-before-compaction）"""
        if not self._long_term or not self._agent_id or not self._user_id:
            return
        try:
            stored = await self._long_term.consolidate(
                agent_id=self._agent_id,
                user_id=self._user_id,
                conversation_id=conversation_id or 0,
                messages=turns,
                min_turns=2,
                max_recent_turns=len(turns),
            )
            if stored > 0:
                logger.info("压缩时记忆提取完成", stored=stored, turns=len(turns))
        except Exception as e:
            logger.warning("压缩时记忆提取失败", error=str(e))

    @staticmethod
    def _static_fallback(dropped_count: int) -> str:
        """LLM 摘要不可用时的静态降级标记"""
        return (
            f"{SUMMARY_PREFIX}\n"
            f"摘要生成不可用。{dropped_count} 条消息被移除以释放上下文空间。"
            "请基于下方最近的消息继续对话。"
        )
