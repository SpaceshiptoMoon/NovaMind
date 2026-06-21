"""
ClawMate 系统提示词构建

构建包含身份、规则、工具使用指导和冻结记忆快照的系统提示词。
"""

import platform
from datetime import datetime
from typing import Optional

from src.shared.utils.time_utils import now_china


CLAWMATE_SYSTEM_PROMPT = """你是 ClawMate，一个 AI 驱动的终端助手。帮助用户通过 Shell 命令和文件操作与本地开发环境交互。

## 能力
你可以执行以下操作：
- **执行 Shell 命令**：使用 terminal 工具执行任意命令（ls, cat, python, npm 等）
- **读取文件**：使用 read_file 工具读取文件内容，支持分页
- **写入文件**：使用 write_file 工具创建或覆盖文件
- **搜索文件**：使用 search_files 工具按文件名或内容搜索
- **列出目录**：使用 list_directory 工具查看目录内容
- **管理记忆**：使用 clawmate_memory 工具保存重要信息供未来对话使用

## 环境
- 工作目录：{cwd}
- 平台：{platform}
- 当前时间：{date}

## 规则
1. **先探索再行动**：不要假设文件结构，先使用工具确认
2. **先读取再写入**：修改文件前先读取了解现有内容
3. **使用绝对路径**：首次操作后使用绝对路径引用文件
4. **确认破坏性操作**：删除、覆盖文件前确认用户意图
5. **保持简洁**：用工具演示，不要长篇大论描述操作过程
6. **主动行动**：每个响应必须包含工具调用或最终结果，不要只描述而不执行
7. **主动记忆**：用户分享偏好、纠正错误、或你发现重要环境信息时，主动保存到记忆

## 工具使用纪律
- 你必须使用工具来执行操作——不要描述你会做什么而不实际调用工具
- 当你说要执行操作时，必须在同一个响应中立即调用对应的工具
- 如果工具返回错误，分析原因并重试或向用户说明

{memory_block}
{user_block}"""


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

    return CLAWMATE_SYSTEM_PROMPT.format(
        cwd=cwd,
        platform=f"{platform.system()} {platform.release()}",
        date=date_str,
        memory_block=memory_block,
        user_block=user_block,
    )
