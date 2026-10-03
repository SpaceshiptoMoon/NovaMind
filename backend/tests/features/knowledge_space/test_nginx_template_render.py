"""docker nginx 模板渲染回归测试。

正反两用例：TLS 开/关两条渲染路径的块剔除与变量注入均正确。
渲染在子进程跑 sh 脚本（Windows 上经 Git Bash），产物落临时目录断言内容。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "docker" / "render-nginx-conf.sh"
TEMPLATE = REPO_ROOT / "docker" / "nginx.template.conf"

sh = shutil.which("sh") or "sh"


def _render(tmp_path: Path, env_extra: dict[str, str]) -> tuple[subprocess.CompletedProcess, str]:
    out_dir = tmp_path / "out"
    env = {
        **os.environ,
        "NGINX_TEMPLATE": str(TEMPLATE),
        "NGINX_OUT_DIR": str(out_dir),
        **env_extra,
    }
    proc = subprocess.run(  # noqa: S603
        [sh, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    content = (out_dir / "nginx.conf").read_text(encoding="utf-8") if (out_dir / "nginx.conf").exists() else ""
    return proc, content


def test_tls_off_keeps_plain_server_and_drops_tls_blocks(tmp_path):
    """未配置证书：剔除 TLS server 与 301 块，保留明文服务（历史行为）。"""
    proc, content = _render(tmp_path, {"NGINX_MAX_BODY_SIZE": "2100m"})
    assert proc.returncode == 0, proc.stderr
    assert "listen 443" not in content
    assert "return 301 https" not in content
    assert "ssl_certificate" not in content
    assert "listen 8080" in content
    assert "client_max_body_size 2100m;" in content
    # 明文 server 必须保留 SPA 与 API 反代（TLS-OFF 块未被误删）
    assert "location ^~ /api/" in content
    assert "try_files $uri $uri/ /index.html;" in content
    # 健康检查两条路径都在
    assert "location /health" in content


def test_tls_on_renders_443_server_and_redirect(tmp_path):
    """配置证书：保留 443 server 与 301，剔除明文服务块，证书路径注入。"""
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("cert")
    key.write_text("key")
    proc, content = _render(
        tmp_path,
        {
            "NGINX_TLS_CERT": str(cert),
            "NGINX_TLS_KEY": str(key),
            "NGINX_MAX_BODY_SIZE": "2g",
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert "listen 443 ssl;" in content
    assert "return 301 https://$host$request_uri;" in content
    assert f"ssl_certificate {cert};" in content
    assert f"ssl_certificate_key {key};" in content
    # 明文 server 只剩 /health（SPA/API/静态/隐藏文件全在 443 server 上）
    assert content.count("try_files $uri $uri/ /index.html;") == 1
    assert content.count("location ^~ /api/") == 1
    assert content.count("location /health") == 1
    assert "client_max_body_size 2g;" in content


def test_tls_on_missing_cert_file_fails_fast(tmp_path):
    """证书路径不存在：渲染失败退出非零（防 nginx crash-loop 无定位信息）。"""
    proc, content = _render(
        tmp_path,
        {
            "NGINX_TLS_CERT": str(tmp_path / "nope.pem"),
            "NGINX_TLS_KEY": str(tmp_path / "nope.key"),
        },
    )
    assert proc.returncode != 0
    assert "不可读" in proc.stderr or "不可读" in proc.stdout


@pytest.mark.skipif(sys.platform == "win32" and not shutil.which("sh"), reason="无 sh 解释器")
def test_marker_pairs_balanced_in_template():
    """模板标记成对出现（BEGIN/END 数量一致），渲染剔除不会残留半开块。"""
    text = TEMPLATE.read_text(encoding="utf-8")
    for marker in ("TLS-REDIRECT", "TLS-OFF", "TLS-SERVER"):
        begins = text.count(f"##{marker}-BEGIN")
        ends = text.count(f"##{marker}-END")
        assert begins == ends == 1, f"{marker} 标记不成对: {begins}/{ends}"
