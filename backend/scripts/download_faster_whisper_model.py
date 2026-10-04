"""统一下载本地 faster-whisper ASR 模型（Systran/faster-whisper-*）。

音频文档未显式配置 asr_model 时默认走本地 faster-whisper 转写（用户裁定
2026-09-23：本地推理免费，部署期预装模型，无云端费用风险）。运行时引擎
默认档位面向生产（large-v3）；开发机低内存场景在 YAML 显式降档。
模型目录解析顺序与运行时一致（audio_utils._resolve_local_whisper_model_dir）：

  --model-dir 参数 > knowledge_base.parsing.local_whisper_model_dir（YAML）
  > --model 档位名 → backend/.cache/faster-whisper/{档位}
  > 默认档位（引擎 DEFAULT_LOCAL_WHISPER_MODEL，生产 large-v3）

支持档位（--model）：tiny / base / small / medium / large-v2 / large-v3。
模型文件（各档位 HF 仓库 Systran/faster-whisper-{slug}）：config.json /
model.bin / tokenizer.json / vocabulary.txt——与 connection_testers.asr
的完整性校验一致。checksum 清单（model_manager.MODEL_CHECKSUMS）已登记的
档位按内容哈希校验；未登记档位降级为大小校验（>0 字节）+ 运行时自检。

本脚本幂等：已存在的文件按 checksum/大小校验后跳过；部署期（deploy.sh）
自动调用，容器内经 compose 挂载卷持久化（backend/.cache/faster-whisper ->
/app/.cache/faster-whisper），重建不丢。

用法（venv 或容器内）：
    python scripts/download_faster_whisper_model.py             # 默认档位
    python scripts/download_faster_whisper_model.py --check     # 只看状态
    python scripts/download_faster_whisper_model.py --model small
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

# 各档位 HF 仓库必需文件（缺一不可；README/.gitattributes 非模型文件）
REQUIRED_FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]

# 默认下载目录（与运行时 _resolve_local_whisper_model_dir 的最终兜底一致）：
# 仓库根 backend/.cache（与 deepdoc 模型同一基准；脚本位于 backend/scripts/，上两级即 backend）
DEFAULT_MODEL_ROOT = Path(__file__).resolve().parents[1] / ".cache" / "faster-whisper"


def resolve_model_slug(cli_model: str | None) -> str:
    """解析目标模型档位：--model 参数 > YAML local_whisper_model > 引擎默认。"""
    if cli_model:
        return cli_model
    try:
        from novamind.setting.yaml_config import get_config

        slug = get_config().knowledge_base.parsing.local_whisper_model
        if slug:
            return slug
    except Exception:
        pass  # 脚本独立运行时 YAML 可能缺失，落到引擎默认
    from novamind.engines.document.media.audio import DEFAULT_LOCAL_WHISPER_MODEL

    return DEFAULT_LOCAL_WHISPER_MODEL


def resolve_model_dir(cli_value: str | None, slug: str) -> Path:
    """解析目标模型目录：--model-dir > YAML 显式目录 > 缓存命名约定（档位名）。"""
    if cli_value:
        return Path(cli_value).expanduser()
    # 与运行时同序：YAML knowledge_base.parsing > 缓存命名约定
    try:
        from novamind.setting.yaml_config import get_config

        configured = get_config().knowledge_base.parsing.local_whisper_model_dir
        if configured:
            return Path(str(configured)).expanduser()
    except Exception:
        pass  # 脚本独立运行时 YAML 可能缺失
    return DEFAULT_MODEL_ROOT / slug


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


def download(model_dir: Path, repo_id: str) -> bool:
    """经 huggingface_hub 下载模型（支持 HF_ENDPOINT 换源），幂等。

    checksum 清单（model_manager.MODEL_CHECKSUMS）已登记的档位按内容哈希
    校验（单一事实源）；未登记档位降级为非空校验（Content-Length 之外的
    「内容损坏」由运行时模型加载自检兜底——CTranslate2 加载损坏文件会直接
    报错，不会产出错误转写）。
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
            if verify_model_checksum(repo_id, filename, target):
                print(f"  [skip] {filename}（已存在，{target.stat().st_size} bytes）", flush=True)
                continue
            # 未登记档位：verify_model_checksum 放行（清单未登记=非损坏判定依据）
            if _checksum_registered(repo_id, filename):
                print(f"  [bad ] {filename}（checksum 不符，重新下载）", flush=True)
                target.unlink(missing_ok=True)
        try:
            print(f"  [down] {filename} ...", flush=True)
            hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=model_dir,
            )
            if _checksum_registered(repo_id, filename) and not verify_model_checksum(
                repo_id, filename, target
            ):
                target.unlink(missing_ok=True)
                raise OSError(f"checksum mismatch after download: {filename}")
        except Exception as exc:
            print(f"  [fail] {filename}: {exc}", flush=True)
            ok = False
    return ok


def _checksum_registered(repo_id: str, filename: str) -> bool:
    """查询 checksum 清单是否登记了该文件（登记→硬校验；未登记→软校验）。"""
    from novamind.engines.document.integrations.deepdoc.vision.model_manager import (
        MODEL_CHECKSUMS,
    )

    return filename in MODEL_CHECKSUMS.get(repo_id, {})


def main() -> int:
    parser = argparse.ArgumentParser(description="下载本地 faster-whisper ASR 模型")
    parser.add_argument(
        "--model",
        choices=["tiny", "base", "small", "medium", "large-v2", "large-v3"],
        help="模型档位（默认按 YAML local_whisper_model / 引擎默认档解析）",
    )
    parser.add_argument("--model-dir", help="目标模型目录（默认按运行时优先级解析）")
    parser.add_argument("--check", action="store_true", help="只检查状态，不下载")
    args = parser.parse_args()

    slug = resolve_model_slug(args.model)
    model_dir = resolve_model_dir(args.model_dir, slug)

    print(f"模型目录: {model_dir}")
    print(f"HuggingFace 仓库: Systran/faster-whisper-{slug}")
    for f in REQUIRED_FILES:
        flag = "✅" if f in check_status(model_dir)["present"] else "❌"
        print(f"  [{flag}] {f}")

    status = check_status(model_dir)
    if status["available"]:
        print("模型已就绪。")
        return 0
    if args.check:
        print(f"模型不完整（缺 {', '.join(status['missing'])}）。", flush=True)
        return 1

    print("开始下载 ...")
    if download(model_dir, f"Systran/faster-whisper-{slug}"):
        final = check_status(model_dir)
        if final["available"]:
            print(f"模型下载完成: {model_dir}")
            return 0
    print("下载未完成——请检查网络后重试（国内可设 HF_ENDPOINT=https://hf-mirror.com）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
