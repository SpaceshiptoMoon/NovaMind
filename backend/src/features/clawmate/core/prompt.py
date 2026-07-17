"""
ClawMate 系统提示词构建

构建包含身份、规则、工具使用指导和冻结记忆快照的系统提示词。

提示词模板统一托管在中央注册表（shared.prompts），见 clawmate_prompts.py 的 clawmate_system。
"""

import platform
from datetime import datetime

from novamind.shared.prompts.templates import PromptManager, PromptTemplate
from novamind.shared.utils.time_utils import now_china


def build_clawmate_system_prompt(
    cwd: str,
    frozen_memory: str = "",
    frozen_user: str = "",
) -> str:
    """构建 ClawMate 系统提示词

    Args:
        cwd: 当前工作目录
        frozen_memory: MEMORY.md 冻结快照内容
        frozen_user: USER.md 冻结快照内容

    Returns:
        完整的系统提示词字符串
    """
    # 记忆块
    memory_block = ""
    if frozen_memory:
        memory_block = (
            "<memory-store>\n"
            "以下是你之前的笔记（只读快照，通过 clawmate_memory 工具的 store='memory' 修改）：\n"
            f"{frozen_memory}\n"
            "</memory-store>"
        )

    user_block = ""
    if frozen_user:
        user_block = (
            "<user-store>\n"
            "以下是用户偏好信息（只读快照，通过 clawmate_memory 工具的 store='user' 修改）：\n"
            f"{frozen_user}\n"
            "</user-store>"
        )

    try:
        date_str = now_china().strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return PromptManager.format_prompt(
        PromptTemplate.CLAWMATE_SYSTEM.value,
        cwd=cwd,
        platform=f"{platform.system()} {platform.release()}",
        date=date_str,
        memory_block=memory_block,
        user_block=user_block,
    )
