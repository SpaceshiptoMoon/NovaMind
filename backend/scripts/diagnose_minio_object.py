"""直接从 MinIO 拉取指定 object 到本地临时文件并跑 diagnose_pdf。

绕开 DB（独立建引擎会 hang），只用 get_config() 取 MinIO 凭证 + minio SDK 直连。

用法（venv）：
    .venv/Scripts/python scripts/diagnose_minio_object.py <object_name> [bucket]
    # bucket 默认 novamind-dev
    # 例：.venv/Scripts/python scripts/diagnose_minio_object.py spaces/1/kbs/2/documents/96/fa9be....pdf
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main(object_name: str, bucket: str) -> None:
    from minio import Minio  # noqa: WPS433

    from novamind.setting.yaml_config import get_config  # noqa: WPS433

    cfg = get_config()
    endpoint = cfg.minio.endpoint
    access_key = cfg.minio.access_key
    secret_key = cfg.minio.secret_key
    secure = cfg.minio.secure
    print(f"MinIO: endpoint={endpoint}, bucket={bucket}, secure={secure}", flush=True)

    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

    suffix = Path(object_name).suffix or ".pdf"
    tmp_path = tempfile.mktemp(suffix=suffix, prefix="minio_diag_")
    print(f"下载 {object_name} -> {tmp_path}", flush=True)
    client.fget_object(bucket, object_name, tmp_path)
    size_mb = Path(tmp_path).stat().st_size / 1024 / 1024
    print(f"下载完成: {size_mb:.1f} MB\n", flush=True)

    try:
        from scripts.diagnose_pdf import diagnose  # noqa: WPS433

        diagnose(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: .venv/Scripts/python scripts/diagnose_minio_object.py <object_name> [bucket]")
        sys.exit(1)
    obj = sys.argv[1]
    bkt = sys.argv[2] if len(sys.argv) > 2 else "novamind-dev"
    main(obj, bkt)