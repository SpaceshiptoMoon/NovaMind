#!/bin/sh
# nginx 配置渲染：把 /etc/nginx/nginx.template.conf 渲染到 /tmp/nginx/nginx.conf，
# 供 supervisord 的 nginx -c 使用。
#
# 为什么不用 nginx 官方镜像的 templates/envsubst 自动机制：本镜像基于 python-slim
# 自装 nginx，由 supervisord 管 nginx 生命周期，渲染必须发生在 nginx 启动之前。
#
# 变量清单（.env 注入，均有安全默认值）：
#   NGINX_MAX_BODY_SIZE  上传体积上限（默认 2100m，与后端 video 模态 2000MB 上限留裕量）
#   NGINX_TLS_CERT/_KEY  TLS 证书/私钥路径。两者都非空才保留 TLS 块（443 server +
#                        明文 server 301）；留空 = 剔除 TLS 块，纯 HTTP 8080（本地/内网形态）
set -eu

# 路径可用环境变量覆盖（供本地测试/CI 校验渲染产物；容器内用默认值）。
TEMPLATE="${NGINX_TEMPLATE:-/etc/nginx/nginx.template.conf}"
OUT_DIR="${NGINX_OUT_DIR:-/tmp/nginx}"
OUT="$OUT_DIR/nginx.conf"
mkdir -p "$OUT_DIR"

: "${NGINX_MAX_BODY_SIZE:=2100m}"

if [ -n "${NGINX_TLS_CERT:-}" ] && [ -n "${NGINX_TLS_KEY:-}" ]; then
    # 启动前校验证书文件可读——缺文件时 nginx 会 crash-loop，
    # 提前给出可定位的错误输出。
    for f in "$NGINX_TLS_CERT" "$NGINX_TLS_KEY"; do
        if [ ! -r "$f" ]; then
            echo "[render-nginx-conf] ERROR: TLS 文件不可读: $f" >&2
            echo "[render-nginx-conf] 请检查挂载与 NGINX_TLS_CERT/_KEY 配置" >&2
            exit 1
        fi
    done
    envsubst '${NGINX_MAX_BODY_SIZE} ${NGINX_TLS_CERT} ${NGINX_TLS_KEY}' \
        < "$TEMPLATE" \
        | sed -e '/##TLS-OFF-BEGIN/,/##TLS-OFF-END/d' > "$OUT"
    echo "[render-nginx-conf] TLS 已启用: cert=$NGINX_TLS_CERT"
else
    envsubst '${NGINX_MAX_BODY_SIZE} ${NGINX_TLS_CERT} ${NGINX_TLS_KEY}' \
        < "$TEMPLATE" \
        | sed -e '/##TLS-SERVER-BEGIN/,/##TLS-SERVER-END/d' \
              -e '/##TLS-REDIRECT-BEGIN/,/##TLS-REDIRECT-END/d' > "$OUT"
    echo "[render-nginx-conf] TLS 未配置（NGINX_TLS_CERT/_KEY 为空），保持纯 HTTP 8080"
fi

echo "[render-nginx-conf] 渲染完成 -> $OUT (client_max_body_size=$NGINX_MAX_BODY_SIZE)"
