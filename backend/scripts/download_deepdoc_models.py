"""统一下载 DeepDoc 全部模型到模型目录。

DeepDoc 共 4 个模型源，本脚本一次性拉齐：

  1. OCR 组    —— 仓库 InfiniFlow/deepdoc：det.onnx / rec.onnx / ocr.res
  2. layout 组 —— 仓库 InfiniFlow/deepdoc：layout.onnx
  3. TSR 组    —— 仓库 InfiniFlow/deepdoc：tsr.onnx
  4. text_concat —— 仓库 InfiniFlow/text_concat_xgb_v1.0：updown_concat_xgb.model
                   （xgboost 段落上下拼接分类器，layout/vision 共用）

模型目录解析顺序（与运行时一致）：
  --model-dir 参数 > DEEPDOC_MODEL_DIR 环境变量 > backend/.cache/deepdoc
text_concat 子目录默认在其下 ./text_concat（或 DEEPDOC_TEXT_CONCAT_MODEL_DIR 覆盖）。

本脚本幂等：已存在的文件不会重复下载（huggingface_hub.snapshot_download 按 etag 跳过）。
仅当本机缺模型或想校验完整性时运行；常规开发模型已随仓库缓存就位。

用法（venv）：
    .venv/Scripts/python scripts/download_deepdoc_models.py             # 下载全部
    .venv/Scripts/python scripts/download_deepdoc_models.py --check     # 只看状态
    .venv/Scripts/python scripts/download_deepdoc_models.py --group ocr # 只下 OCR 组
    .venv/Scripts/python scripts/download_deepdoc_models.py --model-dir D:/models/deepdoc
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows 控制台默认 GBK，强制 UTF-8 避免中文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 各组在中文名与 model_manager 内部 key 之间的映射
GROUP_KEYS: dict[str, str | None] = {
    "ocr": "ocr",
    "layout": "layout",
    "tsr": "tsr",
    "text_concat": "__text_concat__",  # 走 text_concat_model 独立路径
    "all": None,
}


def _print_status(model_dir: Path) -> None:
    from novamind.engines.document.integrations.deepdoc.text_concat_model import (
        get_text_concat_model_status,
    )
    from novamind.engines.document.integrations.deepdoc.vision.model_manager import (
        get_model_status,
    )

    status = get_model_status(model_dir)
    print(f"模型目录: {status['model_dir']}", flush=True)
    print(f"HuggingFace 仓库: {status['repo_id']}", flush=True)
    for group, info in status["groups"].items():
        flag = "✅" if info["available"] else "❌"
        missing = f"（缺 {', '.join(info['missing'])}）" if info["missing"] else ""
        print(f"  [{flag}] {group}: {', '.join(info['present']) or '无'}{missing}", flush=True)

    tc = get_text_concat_model_status(model_dir / "text_concat")
    flag = "✅" if tc["available"] else "❌"
    print(f"  [{flag}] text_concat: {tc['filename']}（仓库 {tc['repo_id']}）", flush=True)
    print(f"         路径: {tc['path']}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 DeepDoc 全部模型")
    parser.add_argument(
        "--group",
        choices=list(GROUP_KEYS.keys()),
        default="all",
        help="只下载指定组（默认 all = 全部）",
    )
    parser.add_argument(
        "--model-dir",
        default=None,
        help="模型目录（默认 DEEPDOC_MODEL_DIR 环境变量或 backend/.cache/deepdoc）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只打印当前状态，不下载",
    )
    args = parser.parse_args()

    from novamind.engines.document.integrations.deepdoc.text_concat_model import (
        download_text_concat_model,
    )
    from novamind.engines.document.integrations.deepdoc.vision.model_manager import (
        default_model_dir,
        download_model_group,
    )

    model_dir = Path(args.model_dir) if args.model_dir else default_model_dir()
    print("=" * 60, flush=True)
    print("DeepDoc 模型下载脚本", flush=True)
    print("=" * 60, flush=True)
    _print_status(model_dir)
    print("-" * 60, flush=True)

    if args.check:
        return 0

    targets = (
        ["ocr", "layout", "tsr", "text_concat"]
        if args.group == "all"
        else [args.group]
    )

    for group in targets:
        print(f"\n→ 下载 {group} 组...", flush=True)
        if group == "text_concat":
            path = download_text_concat_model(model_dir / "text_concat")
            print(f"  text_concat 模型就位: {path}", flush=True)
        else:
            path = download_model_group(group, model_dir)
            print(f"  {group} 组就位: {path}", flush=True)

    print("\n" + "=" * 60, flush=True)
    print("下载完成，最终状态：", flush=True)
    print("=" * 60, flush=True)
    _print_status(model_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())