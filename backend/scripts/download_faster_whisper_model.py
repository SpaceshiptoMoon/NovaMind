"""统一下载本地 faster-whisper ASR 模型（Systran/faster-whisper-tiny）。

音频文档未显式配置 asr_model 时默认走本地 faster-whisper 转写（用户裁定
2026-09-23：本地推理免费，部署期预装模型，无云端费用风险）。模型目录解析
顺序与运行时一致（audio_utils._resolve_local_whisper_model_dir）：

  --model-dir 参数 > knowledge_base.parsing.local_whisper_model_dir（YAML）
  > asr.local_whisper_model_dir > 环境变量 NOVAMIND_LOCAL_WHISPER_MODEL_DIR
  > 默认 ~/.cache/faster-whisper/tiny

模型文件（Systran/faster-whisper-tiny 仓库）：config.json / model.bin /
tokenizer.json / vocabulary.txt——与 connection_testers.asr 的完整性校验一致。

本脚本幂等：已存在的文件按大小校验后跳过；部署期（deploy.sh）自动调用，
容器内经 compose 挂载卷持久化（backend/.cache/faster-whisper ->
/app/.cache/faster-whisper），重建不丢。

用法（venv 或容器内）：
    python scripts/download_faster_whisper_model.py             # 下载
    python scripts/download_faster_whisper_model.py --check     # 只看状态
    python scripts/download_faster_whisper_model.py --model-dir D:/models/whisper
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

# Systran/faster-whisper-tiny 的必需文件（缺一不可；README/.gitattributes 非模型文件）
REQUIRED_FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]

# 默认下载目录（与运行时 _resolve_local_whisper_model_dir 的最终兜底一致）
DEFAULT_MODEL_DIR = Path.home() / ".cache" / "faster-whisper" / "tiny"


def resolve_model_dir(cli_value: str | None) -> Path:
    """解析目标模型目录，优先级与运行时一致。"""
    if cli_value:
        return Path(cli_value).expanduser()
    # 与引擎同序：YAML knowledge_base.parsing > YAML asr > 环境变量 > 默认
    try:
        from novamind.setting.yaml_config import get_config

        cfg = get_config()
        configured = (
            getattr(cfg.knowledge_base.parsing, "local_whisper_model_dir", None)
            or getattr(cfg.asr, "local_whisper_model_dir", None)
        )
        if configured:
            return Path(str(configured)).expanduser()
    except Exception:
        pass  # 脚本独立运行时 YAML 可能缺失，落到环境变量/默认
    import os

    env_dir = os.environ.get("NOVAMIND_LOCAL_WHISPER_MODEL_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return DEFAULT_MODEL_DIR


def check_status(model_dir: Path) -> dict:
    """检查模型文件就绪状态，返回 {available, missing, present}。"""
    present = [f for f in REQUIRED_FILES if (model_dir / f).is_file()]
    missing = [f for f in REQUIRED_FILES if f not in present]
    return {
        "model_dir": model_dir,
        "available": not missing,
        "present": present,
        "missing": missing,
    }


def download(model_dir: Path) -> bool:
    """经 huggingface_hub 下载模型（支持 HF_ENDPOINT 换源），幂等。

    下载/存量文件均按 model_manager.MODEL_CHECKSUMS 校验（单一事实源）：
    Content-Length 之外的「内容损坏但长度对」由 checksum 兜底，失败重下。
    """
    from huggingface_hub import hf_hub_download
    from novamind.engines.document.integrations.deepdoc.vision.model_manager import (
        verify_model_checksum,
    )

    model_dir.mkdir(parents=True, exist_ok=True)
    ok = True
    for filename in REQUIRED_FILES:
        target = model_dir / filename
        if target.is_file() and target.stat().st_size > 0:
            if verify_model_checksum("Systran/faster-whisper-tiny", filename, target):
                print(f"  [skip] {filename}（已存在，{target.stat().st_size} bytes）", flush=True)
                continue
            print(f"  [bad ] {filename}（checksum 不符，重新下载）", flush=True)
            target.unlink(missing_ok=True)
        try:
            print(f"  [down] {filename} ...", flush=True)
            hf_hub_download(
                repo_id="Systran/faster-whisper-tiny",
                filename=filename,
                local_dir=model_dir,
            )
            if not verify_model_checksum("Systran/faster-whisper-tiny", filename, target):
                target.unlink(missing_ok=True)
                raise OSError(f"checksum mismatch after download: {filename}")
        except Exception as exc:
            print(f"  [fail] {filename}: {exc}", flush=True)
            ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="下载本地 faster-whisper ASR 模型")
    parser.add_argument("--model-dir", help="目标模型目录（默认按运行时优先级解析）")
    parser.add_argument("--check", action="store_true", help="只检查状态，不下载")
    args = parser.parse_args()

    model_dir = resolve_model_dir(args.model_dir)
    status = check_status(model_dir)

    print(f"模型目录: {model_dir}")
    print("HuggingFace 仓库: Systran/faster-whisper-tiny")
    for f in REQUIRED_FILES:
        flag = "✅" if f in status["present"] else "❌"
        print(f"  [{flag}] {f}")

    if status["available"]:
        print("模型已就绪。")
        return 0
    if args.check:
        print(f"模型不完整（缺 {', '.join(status['missing'])}）。", flush=True)
        return 1

    print("开始下载 ...")
    if download(model_dir):
        final = check_status(model_dir)
        if final["available"]:
            print(f"模型下载完成: {model_dir}")
            return 0
    print("下载未完成——请检查网络后重试（国内可设 HF_ENDPOINT=https://hf-mirror.com）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
