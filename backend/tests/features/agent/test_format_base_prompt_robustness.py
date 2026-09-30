"""_format_base_prompt 模板健壮性回归测试（红队审计 P2）。

用户自定义 system_prompt 含 {tools} 占位符且同时含其它 {...} 字面量
（JSON 示例/代码模板）时，str.format 抛 KeyError 曾让该 agent 全部对话 500。
"""
import pytest

pytestmark = pytest.mark.unit


def _svc():
    from novamind.features.agent.services.chat_service import AgentChatService
    return AgentChatService.__new__(AgentChatService)


def test_format_with_only_known_placeholders() -> None:
    """相邻正常场景：只有已知占位符时走 str.format 正常替换"""
    svc = _svc()
    out = svc._format_base_prompt(
        "你是助手，可用工具：{tools}，今天是 {current_date}。", ["web_search"]
    )
    assert "web_search" in out
    assert "{tools}" not in out
    assert "{current_date}" not in out


def test_format_survives_foreign_braces() -> None:
    """正例：模板含其它 {...} 字面量不再 KeyError，两个已知占位符仍被替换"""
    svc = _svc()
    template = (
        '你是助手。输出 JSON：{"key": "{tools}", "date": "{current_date}"}，'
        '禁止输出 {unexpected_field}。'
    )
    out = svc._format_base_prompt(template, ["web_search"])
    assert "web_search" in out
    assert "{tools}" not in out
    assert "{current_date}" not in out
    assert "{unexpected_field}" in out  # 外来字面量原样保留


def test_no_tools_placeholder_passthrough() -> None:
    """无 {tools} 占位符的模板原样返回（不触发 format）"""
    svc = _svc()
    raw = "你是翻译助手，含 {json} 字面量但不替换。"
    assert svc._format_base_prompt(raw, []) == raw
