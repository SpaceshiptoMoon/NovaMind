"""
记忆存储管理

参考 Hermes 的 MemoryStore 简化版，管理 MEMORY.md 和 USER.md：
- MEMORY.md：AI 助手的个人笔记（环境事实、项目约定、工具技巧）
- USER.md：用户偏好（沟通风格、工作习惯、技术栈）

冻结快照模式：
- session 创建时读取文件内容作为快照注入 system prompt
- 运行时通过 memory 工具修改文件（持久化到磁盘）
- 快照在 session 生命周期内不更新（保持 system prompt 稳定）

安全加固（参考 Hermes）：
- 原子写入：tempfile + fsync + os.replace（防并发写入丢数据）
- asyncio.Lock：防止同一 session 内并发操作
- 去重加载：每次读取时保序去重
- 跨会话安全：每次操作前从磁盘重新加载
"""

import asyncio
import json
import os
import re
import tempfile
from typing import List, Optional

from novamind.features.clawmate.core.file_operations import FileOperations
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# 条目分隔符
ENTRY_DELIMITER = "\n---\n"

# 字符限制
MEMORY_CHAR_LIMIT = 4000
USER_CHAR_LIMIT = 2000

# 安全扫描模式（参考 Hermes _MEMORY_THREAT_PATTERNS 简化版）
_THREAT_PATTERNS = [
    # 逃逸标签（防止从 memory block 中逃逸）
    (r"</(memory-store|user-store)>", "escape_tag"),
    # 注入标签
    (r"<system\b", "system_tag"),
    (r"<instructions\b", "instructions_tag"),
    # 角色劫持
    (r"ignore\s+(previous|all|above|prior)\s+instructions", "prompt_injection"),
    (r"you\s+are\s+now\s+", "role_hijack"),
    (r"disregard\s+(your|all|any)\s+(instructions|rules)", "disregard_rules"),
    # 数据窃取
    (r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfil_curl"),
    (r"wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfil_wget"),
]

# 不可见 Unicode 字符
_INVISIBLE_CHARS = {
    '​', '‌', '‍', '⁠', '﻿',
    '‪', '‫', '‬', '‭', '‮',
}


def _scan_content(content: str) -> Optional[str]:
    """扫描内容安全性。返回错误信息或 None（安全）。"""
    # 检查不可见字符
    for char in _INVISIBLE_CHARS:
        if char in content:
            return f"内容包含不可见 Unicode 字符 U+{ord(char):04X}，可能为注入攻击"

    # 检查威胁模式
    for pattern, threat_id in _THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return f"内容匹配威胁模式 '{threat_id}'，记忆内容会被注入到系统提示词中，不允许包含注入或窃取载荷"

    return None


class MemoryStore:
    """管理 MEMORY.md 和 USER.md 的读写操作

    线程安全：
    - asyncio.Lock 防止同一 session 内并发操作
    - 原子写入防数据丢失
    - 每次操作前从磁盘重新加载
    """

    def __init__(self, workspace_root: str, file_ops: FileOperations):
        """
        Args:
            workspace_root: 工作区根目录
            file_ops: 文件操作实例（通过 Shell 命令读写文件）
        """
        self.workspace_root = workspace_root
        self.file_ops = file_ops
        self.memory_path = os.path.join(workspace_root, "MEMORY.md")
        self.user_path = os.path.join(workspace_root, "USER.md")
        self._lock = asyncio.Lock()

    def load_snapshot(self) -> tuple:
        """加载冻结快照（session 创建时调用一次）

        Returns:
            (memory_content, user_content) 元组
        """
        memory_content = self._read_file_content(self.memory_path)
        user_content = self._read_file_content(self.user_path)

        logger.debug(
            "记忆快照已加载",
            memory_chars=len(memory_content),
            user_chars=len(user_content),
        )

        return memory_content, user_content

    async def execute(
        self,
        action: str,
        store: str,
        content: Optional[str] = None,
        old_content: Optional[str] = None,
    ) -> str:
        """执行记忆操作（加锁 + 从磁盘重新加载）

        Args:
            action: "add" | "replace" | "remove"
            store: "memory" | "user"
            content: 新内容（add/replace 必填）
            old_content: 旧内容子串（replace/remove 必填）

        Returns:
            JSON 格式结果字符串
        """
        async with self._lock:
            try:
                return await self._execute_locked(action, store, content, old_content)
            except Exception as e:
                logger.error("记忆操作失败", action=action, store=store, error=str(e))
                return json.dumps({"success": False, "error": f"操作失败: {str(e)}"}, ensure_ascii=False)

    async def _execute_locked(
        self,
        action: str,
        store: str,
        content: Optional[str],
        old_content: Optional[str],
    ) -> str:
        """加锁状态下的操作执行"""
        if store not in ("memory", "user"):
            return json.dumps({"success": False, "error": f"无效的存储目标 '{store}'"}, ensure_ascii=False)

        char_limit = MEMORY_CHAR_LIMIT if store == "memory" else USER_CHAR_LIMIT
        file_path = self.memory_path if store == "memory" else self.user_path

        if action == "add":
            return await self._action_add(store, file_path, content, char_limit)
        elif action == "replace":
            return await self._action_replace(store, file_path, old_content, content, char_limit)
        elif action == "remove":
            return await self._action_remove(store, file_path, old_content)
        else:
            return json.dumps({"success": False, "error": f"未知操作 '{action}'，可用：add, replace, remove"}, ensure_ascii=False)

    async def _action_add(
        self, store: str, file_path: str, content: Optional[str], char_limit: int
    ) -> str:
        """添加条目"""
        if not content or not content.strip():
            return json.dumps({"success": False, "error": "内容不能为空"}, ensure_ascii=False)

        content = content.strip()

        # 安全扫描
        scan_error = _scan_content(content)
        if scan_error:
            return json.dumps({"success": False, "error": scan_error}, ensure_ascii=False)

        # 从磁盘重新读取（跨会话安全）
        entries = self._get_entries(file_path)

        # 拒绝重复
        if content in entries:
            return json.dumps({"success": True, "message": "条目已存在（未重复添加）", "store": store}, ensure_ascii=False)

        # 检查字符限制
        new_entries = entries + [content]
        new_total = len(ENTRY_DELIMITER.join(new_entries))
        if new_total > char_limit:
            current = len(ENTRY_DELIMITER.join(entries)) if entries else 0
            return json.dumps({
                "success": False,
                "error": f"存储已达 {current}/{char_limit} 字符，添加此条目（{len(content)} 字符）将超出限制。请先删除或替换现有条目。",
                "usage": f"{current}/{char_limit}",
            }, ensure_ascii=False)

        # 追加条目
        entries.append(content)
        await self._write_entries(file_path, entries)

        return self._success_response(store, entries, char_limit, "条目已添加")

    async def _action_replace(
        self,
        store: str,
        file_path: str,
        old_content: Optional[str],
        new_content: Optional[str],
        char_limit: int,
    ) -> str:
        """替换条目"""
        if not old_content or not old_content.strip():
            return json.dumps({"success": False, "error": "old_content 不能为空"}, ensure_ascii=False)
        if not new_content or not new_content.strip():
            return json.dumps({"success": False, "error": "new_content 不能为空，使用 remove 来删除条目"}, ensure_ascii=False)

        new_content = new_content.strip()
        old_text = old_content.strip()

        # 安全扫描新内容
        scan_error = _scan_content(new_content)
        if scan_error:
            return json.dumps({"success": False, "error": scan_error}, ensure_ascii=False)

        # 从磁盘重新读取
        entries = self._get_entries(file_path)

        # 查找匹配
        matches = [(i, e) for i, e in enumerate(entries) if old_text in e]
        if not matches:
            return json.dumps({"success": False, "error": f"未找到匹配 '{old_text}' 的条目"}, ensure_ascii=False)

        if len(matches) > 1:
            unique = set(e for _, e in matches)
            if len(unique) > 1:
                previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
                return json.dumps({
                    "success": False,
                    "error": f"多个条目匹配 '{old_text}'，请提供更具体的匹配文本",
                    "matches": previews,
                }, ensure_ascii=False)

        idx = matches[0][0]
        entries[idx] = new_content

        # 检查字符限制
        new_total = len(ENTRY_DELIMITER.join(entries))
        if new_total > char_limit:
            return json.dumps({
                "success": False,
                "error": f"替换后将达 {new_total}/{char_limit} 字符，超限。请缩短新内容或先删除其他条目。",
            }, ensure_ascii=False)

        await self._write_entries(file_path, entries)
        return self._success_response(store, entries, char_limit, "条目已替换")

    async def _action_remove(
        self, store: str, file_path: str, old_content: Optional[str]
    ) -> str:
        """删除条目"""
        if not old_content or not old_content.strip():
            return json.dumps({"success": False, "error": "old_content 不能为空"}, ensure_ascii=False)

        old_text = old_content.strip()

        # 从磁盘重新读取
        entries = self._get_entries(file_path)

        matches = [(i, e) for i, e in enumerate(entries) if old_text in e]
        if not matches:
            return json.dumps({"success": False, "error": f"未找到匹配 '{old_text}' 的条目"}, ensure_ascii=False)

        if len(matches) > 1:
            unique = set(e for _, e in matches)
            if len(unique) > 1:
                previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
                return json.dumps({
                    "success": False,
                    "error": f"多个条目匹配 '{old_text}'，请提供更具体的匹配文本",
                    "matches": previews,
                }, ensure_ascii=False)

        idx = matches[0][0]
        entries.pop(idx)
        await self._write_entries(file_path, entries)
        return self._success_response(store, entries, 0, "条目已删除")

    def _read_file_content(self, path: str) -> str:
        """通过 Shell 读取文件内容（同步，在 session 初始化时调用）"""
        try:
            result = self.file_ops.env.execute(f"cat {self._shell_safe(path)} 2>/dev/null || echo ''")
            if result["returncode"] == 0:
                return result["output"].strip()
        except Exception:
            pass
        return ""

    def _get_entries(self, file_path: str) -> List[str]:
        """从文件读取条目列表（保序去重）"""
        content = self._read_file_content(file_path)
        if not content:
            return []
        entries = [e.strip() for e in content.split(ENTRY_DELIMITER)]
        entries = [e for e in entries if e]

        # 保序去重（参考 Hermes dict.fromkeys()）
        seen = set()
        deduped = []
        for e in entries:
            if e not in seen:
                seen.add(e)
                deduped.append(e)

        return deduped

    async def _write_entries(self, file_path: str, entries: List[str]):
        """将条目列表写入文件（原子写入）"""
        content = ENTRY_DELIMITER.join(entries) if entries else ""
        await asyncio.to_thread(self._atomic_write, file_path, content)

    @staticmethod
    def _atomic_write(path: str, content: str):
        """原子写入：tempfile + fsync + os.replace

        保证：
        - 写入过程中断不会损坏文件（先写临时文件再原子替换）
        - 并发读取者始终看到完整文件
        """
        parent = os.path.dirname(path)
        if not parent:
            parent = "."

        # 确保目录存在
        os.makedirs(parent, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            dir=parent, suffix=".tmp", prefix=".mem_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)  # 原子替换
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _shell_safe(path: str) -> str:
        """Shell 安全路径引用"""
        import shlex
        return shlex.quote(os.path.normpath(path))

    @staticmethod
    def _success_response(
        store: str, entries: List[str], char_limit: int, message: str
    ) -> str:
        """生成成功响应"""
        current = len(ENTRY_DELIMITER.join(entries)) if entries else 0
        if char_limit > 0:
            usage = f"{current}/{char_limit}"
        else:
            # remove 操作不传 limit，用对应存储的实际 limit
            limit = MEMORY_CHAR_LIMIT if store == "memory" else USER_CHAR_LIMIT
            usage = f"{current}/{limit}"

        return json.dumps({
            "success": True,
            "store": store,
            "message": message,
            "entries": entries,
            "usage": usage,
            "entry_count": len(entries),
        }, ensure_ascii=False)
