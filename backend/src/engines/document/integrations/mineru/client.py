"""MinerU 外部解析引擎客户端（PDF strategy=mineru 的引擎侧适配层）。

适配 MinerU 4.x「常驻服务 + CLI 客户端」形态：``mineru server start`` 起本地
常驻服务（模型驻留），本模块经 ``mineru parse`` 子进程提交解析并落产物。
MinerU 本体不在主进程依赖树内（独立环境安装，避免依赖树冲突）；配置由宿主
注入（引擎侧零 env 依赖、零模型名硬编码），引擎未安装或执行失败显式上抛，
不做任何静默降级。
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class MineruNotAvailableError(Exception):
    """MinerU 引擎未安装/未配置，或本地解析服务未运行。不可重试。"""


class MineruExecutionError(Exception):
    """MinerU 子进程执行失败（非零退出/超时/产物缺失）。通常可重试。"""


@dataclass(frozen=True)
class MineruEngineConfig:
    """宿主注入的引擎运行参数（源自 YAML mineru 段，经 build_engine_mineru_config）。"""

    # MinerU 独立环境的 mineru 可执行文件完整路径；空串 = 引擎未安装
    cli_path: str = ""
    # 解析档位：flash（最快）/ basic / standard / advanced（质量最高）
    tier: str = "flash"
    # 单文档解析超时（秒）：同时作为 CLI --wait 与子进程硬超时（后者加裕量）
    timeout: int = 600
    # 透传给 mineru CLI 的额外参数
    extra_args: tuple[str, ...] = ()

    @property
    def subprocess_timeout(self) -> int:
        """子进程硬超时：比 CLI --wait 多留 60s 收尾裕量。"""
        return self.timeout + 60


_PAGE_MARKER = re.compile(r"<!--\s*page\s+\d+\s+of\s+(\d+)\s*-->")
_SERVER_NOT_RUNNING_MARK = "服务未运行"


@dataclass(frozen=True)
class MineruParseResult:
    """MinerU 解析产物：markdown 全文（含页标记）+ 页数。"""

    full_text: str
    page_count: int


def parse_pdf_sync(
    content: bytes,
    file_name: str,
    config: MineruEngineConfig,
) -> MineruParseResult:
    """同步执行 MinerU CLI 解析一个 PDF（调用方负责经 asyncio.to_thread 包装）。

    Args:
        content: PDF 文件字节。
        file_name: 原始文件名（仅用于临时目录内的文件命名）。
        config: 宿主注入的引擎运行配置。

    Returns:
        解析产物（markdown 全文 + 页数）。

    Raises:
        MineruNotAvailableError: cli_path 为空/可执行文件不存在，或本地
            mineru 服务未运行（提示先执行 mineru server start）。
        MineruExecutionError: 子进程非零退出、超时或产物缺失。
    """
    if not config.cli_path:
        raise MineruNotAvailableError(
            "MinerU 引擎未配置：请在配置文件 mineru.cli_path 填入 MinerU 独立环境的"
            " mineru 可执行文件路径。安装方式：uv venv <venv> && uv pip install "
            '--python <venv> "mineru[core]"；并用 <venv>/mineru server start 启动本地解析服务'
        )
    cli = Path(config.cli_path)
    if not cli.is_file():
        raise MineruNotAvailableError(
            f"MinerU 可执行文件不存在: {config.cli_path}——请检查 mineru.cli_path 配置"
        )

    with tempfile.TemporaryDirectory(prefix="mineru_parse_") as tmp:
        tmp_dir = Path(tmp)
        input_path = tmp_dir / (file_name or "input.pdf")
        input_path.write_bytes(content)
        output_path = tmp_dir / "result.md"

        # --force：同字节文件的 MinerU 内容寻址缓存会掩盖 tier/模型变更，禁用缓存
        # 保证「配置 → 产物」语义诚实；--wait 与子进程超时双保险防挂死
        cmd = [
            str(cli),
            "parse", str(input_path),
            "--output", str(output_path),
            "--tier", config.tier,
            "--force",
            "--wait", str(config.timeout),
            *config.extra_args,
        ]
        try:
            proc = subprocess.run(  # noqa: S603——命令来自宿主配置而非用户输入
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=config.subprocess_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MineruExecutionError(
                f"MinerU 解析超时（wait={config.timeout}s，tier={config.tier}）"
            ) from exc
        except OSError as exc:
            raise MineruNotAvailableError(f"MinerU 可执行文件无法启动: {exc}") from exc

        combined = (proc.stdout or "") + (proc.stderr or "")
        if _SERVER_NOT_RUNNING_MARK in combined:
            raise MineruNotAvailableError(
                "本地 mineru 服务未运行——请先执行 "
                f"{config.cli_path} server start（服务常驻模型，解析走本地队列）"
            )
        if proc.returncode != 0:
            raise MineruExecutionError(
                f"MinerU 退出码 {proc.returncode}：{combined[-400:]}"
            )
        if not output_path.is_file():
            raise MineruExecutionError(
                f"MinerU 未产出 markdown（可能解析超时未完成）：{combined[-300:]}"
            )

        full_text = output_path.read_text(encoding="utf-8", errors="replace")
        if not full_text.strip():
            raise MineruExecutionError("MinerU 产物 markdown 为空")

        page_count = _extract_page_count(full_text)
        # 页标记是 MinerU 内部结构契约（<!-- page N of M -->），对检索是噪音——
        # 提取页数后从入库全文剥离
        full_text = _PAGE_MARKER.sub("", full_text)

        return MineruParseResult(full_text=full_text, page_count=page_count)


def _extract_page_count(full_text: str) -> int:
    """从页标记 ``<!-- page N of M -->`` 提取总页数；无标记返回 0（未知）。"""
    matches = _PAGE_MARKER.findall(full_text)
    return int(matches[0]) if matches else 0


async def parse_pdf(
    content: bytes,
    file_name: str,
    config: MineruEngineConfig,
) -> MineruParseResult:
    """异步入口：to_thread 包装同步子进程执行，不阻塞事件循环。"""
    return await asyncio.to_thread(parse_pdf_sync, content, file_name, config)
