"""
技能安全检查器 — 规则 + LLM 双重审查

防止恶意技能通过提示词注入攻击 Agent 系统提示词
"""
import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from src.core.middleware.structured_logging import get_logger
from src.features.skill.models.skill import ReviewStatus
from src.shared.ai_models.base_model import BaseLLM
from src.shared.prompts import PromptTemplate, PromptManager

logger = get_logger(__name__)

# 注入模式正则
_INJECTION_PATTERNS = [
    (r"ignore\s+(all\s+)?previous\s+instructions", "忽略前文指令"),
    (r"forget\s+(all\s+)?previous", "遗忘前文"),
    (r"you\s+are\s+now\s+a", "身份重定义"),
    (r"new\s+instructions?\s*:", "新指令注入"),
    (r"system\s*prompt\s*(override|replace|ignore|change)", "系统提示词覆盖"),
    (r"<\/?(system|developer|assistant|user)>", "XML 标签注入"),
    (r"\\u[0-9a-fA-F]{4}", "Unicode 转义混淆"),
    (r"jailbreak", "越狱关键词"),
    (r"DAN\s+mode", "DAN 模式注入"),
    (r"developer\s+mode", "开发者模式注入"),
    (r"sudo\s+mode", "sudo 模式注入"),
]

# 编译正则
_COMPILED_PATTERNS = [
    (re.compile(p, re.IGNORECASE | re.MULTILINE), label)
    for p, label in _INJECTION_PATTERNS
]

# LLM 审查超时（秒）
_LLM_REVIEW_TIMEOUT = 15


@dataclass
class RuleCheckResult:
    """规则检查结果"""
    passed: bool
    matches: List[dict] = field(default_factory=list)


@dataclass
class LLMCheckResult:
    """LLM 审查结果"""
    level: str = "safe"  # safe / suspicious / dangerous
    reason: str = ""
    raw_response: str = ""


@dataclass
class SecurityCheckResult:
    """综合安全检查结果"""
    status: int = ReviewStatus.APPROVED
    rule_result: Optional[RuleCheckResult] = None
    llm_result: Optional[LLMCheckResult] = None


class SkillSecurityChecker:
    """技能安全检查器"""

    def __init__(self, llm_client: Optional[BaseLLM] = None):
        """
        Args:
            llm_client: 可选的 BaseLLM 实例，用于 LLM 内容审查。
                        不传入则只做规则检查。
        """
        self._llm_client = llm_client

    async def check_rules(
        self, body_markdown: str, frontmatter_raw: str = "",
    ) -> RuleCheckResult:
        """
        正则规则检查

        扫描 body 和 frontmatter 是否匹配已知注入模式
        """
        content = f"{frontmatter_raw}\n{body_markdown}"
        matches = []

        for pattern, label in _COMPILED_PATTERNS:
            found = pattern.findall(content)
            if found:
                matches.append({
                    "pattern": label,
                    "count": len(found),
                })

        return RuleCheckResult(
            passed=len(matches) == 0,
            matches=matches,
        )

    async def check_llm(
        self, body_markdown: str, frontmatter_raw: str = "",
    ) -> Optional[LLMCheckResult]:
        """
        LLM 审查 — 使用 BaseLLM 分析内容安全性

        Returns:
            LLMCheckResult 或 None（如果 LLM 不可用或超时）
        """
        if not self._llm_client:
            return None

        try:
            prompt = PromptManager.format_prompt(
                PromptTemplate.SKILL_SECURITY_REVIEW.value,
                frontmatter=frontmatter_raw[:2000],
                body=body_markdown[:4000],
            )
            response = await asyncio.wait_for(
                self._llm_client.generate_text(
                    prompt=prompt,
                    temperature=0.1,
                    max_tokens=200,
                    response_format={"type": "json_object"},
                ),
                timeout=_LLM_REVIEW_TIMEOUT,
            )
            return self._parse_llm_response(response)
        except asyncio.TimeoutError:
            logger.error("LLM 安全审查超时", security_implication="LLM审查跳过，规则检查通过则自动批准")
            return None
        except Exception as e:
            logger.error("LLM 安全审查失败", error=str(e), security_implication="LLM审查跳过，规则检查通过则自动批准")
            return None

    async def check(
        self, body_markdown: str, frontmatter_raw: str = "",
    ) -> SecurityCheckResult:
        """
        综合安全检查：规则 + LLM

        流程：
          1. 规则检查，如果命中危险模式直接 REJECTED
          2. LLM 审查（如果可用）
          3. 综合判定：safe→APPROVED, suspicious→SUSPICIOUS, dangerous→REJECTED
        """
        result = SecurityCheckResult()

        # Step 1: 规则检查
        rule_result = await self.check_rules(body_markdown, frontmatter_raw)
        result.rule_result = rule_result

        if rule_result.matches and len(rule_result.matches) >= 3:
            # 命中 3 条以上规则，直接拒绝
            result.status = ReviewStatus.REJECTED
            return result

        # Step 2: LLM 审查
        llm_result = await self.check_llm(body_markdown, frontmatter_raw)
        result.llm_result = llm_result

        if llm_result:
            if llm_result.level == "dangerous":
                result.status = ReviewStatus.REJECTED
            elif llm_result.level == "suspicious":
                result.status = ReviewStatus.SUSPICIOUS
            else:
                result.status = ReviewStatus.APPROVED
        else:
            # LLM 不可用或超时时，标记为 SUSPICIOUS 需人工审核
            result.status = ReviewStatus.SUSPICIOUS

        # 如果规则检查有少量命中，升级为 SUSPICIOUS
        if result.status == ReviewStatus.APPROVED and rule_result.matches:
            result.status = ReviewStatus.SUSPICIOUS

        return result

    def _parse_llm_response(self, response: str) -> LLMCheckResult:
        """解析 LLM 审查响应"""
        result = LLMCheckResult(raw_response=response)

        try:
            # response_format=json_object 时 LLM 直接返回 JSON
            data = json.loads(response)
            safe = data.get("safe", True)
            level = data.get("level", "safe")
            reason = data.get("reason", "")

            result.level = level if level in ("safe", "suspicious", "dangerous") else "safe"
            if not safe and result.level == "safe":
                result.level = "suspicious"
            result.reason = reason
        except (json.JSONDecodeError, KeyError):
            # JSON 解析失败，尝试正则提取
            json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    safe = data.get("safe", True)
                    level = data.get("level", "safe")
                    result.level = level if level in ("safe", "suspicious", "dangerous") else "safe"
                    if not safe and result.level == "safe":
                        result.level = "suspicious"
                    result.reason = data.get("reason", "")
                except (json.JSONDecodeError, KeyError):
                    result.level = "suspicious"
                    result.reason = "LLM 响应解析失败"
            else:
                result.level = "suspicious"
                result.reason = "LLM 响应解析失败"

        return result
