"""MinerU 外部引擎接入回归（适配器 + 策略流转 + fail-fast）。

覆盖四层正反用例：
- 适配器 fail-fast：cli_path 缺失 / 可执行文件不存在 / 本地服务未运行，
  全部显式报错不静默降级；
- 适配器产物解析：假 CLI 全流程（写 markdown 产物）、页标记解析、
  非零退出报可重试错误；
- 策略归一：resolve_text_parsing_strategy 接受 mineru；
- schema：PdfParsingConfig 接受 strategy=mineru，运行时配置传播不丢。
"""
import sys
from pathlib import Path

import pytest

# 假 CLI 是 Windows .bat（type/GBK 语义），POSIX 无法执行——整模块 Windows 专属
pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="fake CLI 为 Windows .bat，POSIX 不适用"
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.integrations.mineru import (
    MineruEngineConfig,
    MineruExecutionError,
    MineruNotAvailableError,
    parse_pdf_sync,
)
from novamind.engines.document.integrations.mineru.client import _extract_page_count
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    PdfParsingConfig,
    build_runtime_parsing_config,
)
from novamind.features.knowledge_space.services.document_pipeline import (
    resolve_text_parsing_strategy,
)

# 注意：模块级 pytestmark 只能赋值一次（后赋值会覆盖 skipif）——多标记用列表
pytestmark = [
    pytest.mark.skipif(
        sys.platform != "win32", reason="fake CLI 为 Windows .bat，POSIX 不适用"
    ),
    pytest.mark.unit,
]


# ---------- 适配器：fail-fast ----------

def test_empty_cli_path_raises_not_available():
    """cli_path 为空 = 引擎未安装：显式报错并带安装指引，不走任何兜底。"""
    with pytest.raises(MineruNotAvailableError, match="mineru.cli_path"):
        parse_pdf_sync(b"%PDF-1.4 fake", "a.pdf", MineruEngineConfig(cli_path=""))


def test_missing_executable_raises_not_available():
    """cli_path 指向不存在的文件：显式报错而非 OSError 冒泡。"""
    with pytest.raises(MineruNotAvailableError, match="不存在"):
        parse_pdf_sync(
            b"%PDF-1.4 fake", "a.pdf",
            MineruEngineConfig(cli_path="Z:/no/such/mineru.exe"),
        )


def _fake_cli(tmp_path: Path, body: str) -> str:
    """伪造 mineru CLI（Windows .bat）：%4 是 --output 的输出路径。"""
    cli = tmp_path / "fake_mineru.bat"
    cli.write_text(body, encoding="gbk", errors="replace")
    return str(cli)


def test_server_not_running_raises_not_available(tmp_path):
    """CLI 报「服务未运行」（退出码 0 也要识别）→ 不可重试错误并指路。

    假 CLI 经 type 输出 UTF-8 中文消息文件，模拟真实 MinerU 的输出形态。
    """
    msg = tmp_path / "msg.txt"
    msg.write_text(
        "错误: 本地 mineru 服务未运行。请先运行 'mineru server start'。",
        encoding="utf-8",
    )
    cli = _fake_cli(tmp_path, f'@echo off\r\ntype "{msg}"\r\nexit /b 0\r\n')
    with pytest.raises(MineruNotAvailableError, match="server start"):
        parse_pdf_sync(b"%PDF-1.4 fake", "a.pdf", MineruEngineConfig(cli_path=cli))


def test_nonzero_exit_raises_execution_error(tmp_path):
    """非零退出且无服务标记 → 可重试的执行错误。"""
    cli = _fake_cli(tmp_path, "@echo off\r\necho model crashed\r\nexit /b 1\r\n")
    with pytest.raises(MineruExecutionError, match="退出码 1"):
        parse_pdf_sync(b"%PDF-1.4 fake", "a.pdf", MineruEngineConfig(cli_path=cli))


def test_full_flow_parses_markdown_output(tmp_path):
    """全流程正例：假 CLI 产出带页标记的 markdown → 页数正确、标记剥离、正文保留。"""
    md = tmp_path / "prepared.md"
    md.write_text("<!-- page 1 of 2 -->\nMINERU_OUTPUT_TEXT\n", encoding="utf-8")
    cli = _fake_cli(tmp_path, f'@echo off\r\ncopy /y "{md}" "%~4" >nul\r\n')
    result = parse_pdf_sync(
        b"%PDF-1.4 fake", "a.pdf", MineruEngineConfig(cli_path=cli, tier="flash")
    )
    assert "MINERU_OUTPUT_TEXT" in result.full_text
    assert result.page_count == 2
    assert "page 1 of 2" not in result.full_text, "页标记不应进入入库全文"


# ---------- 页标记解析 ----------

def test_extract_page_count_from_marker():
    assert _extract_page_count("<!-- page 1 of 7 -->\n正文") == 7
    assert _extract_page_count("无标记文本") == 0


# ---------- 策略归一与 schema 流转 ----------

def test_resolve_strategy_accepts_mineru():
    """runtime 策略归一接受 mineru。"""
    assert resolve_text_parsing_strategy({"strategy": "mineru"}, document_id=1) == "mineru"


def test_pdf_schema_accepts_mineru_strategy():
    """schema 接受 strategy=mineru 且运行时配置传播不丢。"""
    cfg = PdfParsingConfig(strategy="mineru")
    assert cfg.strategy == "mineru"
    runtime = build_runtime_parsing_config(
        {"text": {"pdf": {"strategy": "mineru"}}}, file_type="pdf"
    )
    assert runtime["strategy"] == "mineru"
