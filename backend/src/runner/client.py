"""runner 客户端主体：出站 WSS、配对/重连、心跳、收 call 执行回 result。

生命周期（设计文档 §3.2）：启动 → 出站连接 → hello（pairing_token 或
持久化 device_key）→ 消息循环；断线指数退避重连（1s 起、上限 60s）。
device_key 明文持久化在用户目录 `~/.novamind-runner/credentials.json`。
"""
import asyncio
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

import websockets
from novamind.runner.ops import execute_local

RUNNER_VERSION = "0.1.0"
_HEARTBEAT_SECONDS = 15
_RECONNECT_BASE = 1.0
_RECONNECT_CAP = 60.0
_CREDENTIALS_PATH = Path.home() / ".novamind-runner" / "credentials.json"


def _load_credentials() -> dict[str, Any]:
    try:
        return json.loads(_CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_credentials(data: dict[str, Any]) -> None:
    _CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CREDENTIALS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:  # 密钥文件只归当前用户（POSIX）；Windows 由目录 ACL 兜底
        os.chmod(_CREDENTIALS_PATH, 0o600)
    except OSError:
        pass


def _detect_os() -> str:
    s = platform.system().lower()
    return s if s in ("windows", "darwin", "linux") else "unknown"


class RunnerClient:
    """一条到云端的 runner 连接会话（含重连循环）。"""

    def __init__(self, server_url: str, pairing_token: str | None, root: str):
        self.server_url = server_url.rstrip("/")
        self.pairing_token = pairing_token
        self.root = root
        self.os_type = _detect_os()
        self.device_key: str | None = None

    def _ws_url(self) -> str:
        # HTTP(S) → WS(S)：runner 侧只接受 ws:// ws(s):// 之外还容忍 https 前缀直填
        url = self.server_url
        for scheme, repl in (("https://", "wss://"), ("http://", "ws://")):
            if url.startswith(scheme):
                url = repl + url[len(scheme):]
                break
        return f"{url}/api/v1/agent/runner/ws"

    def _credential(self) -> str:
        if self.device_key:
            return self.device_key
        creds = _load_credentials()
        return str(creds.get("device_key") or self.pairing_token or "")

    async def run_forever(self) -> None:
        """重连循环：指数退避，device_key 落地后配对 token 即弃用。"""
        backoff = _RECONNECT_BASE
        while True:
            try:
                await self._run_once()
                backoff = _RECONNECT_BASE  # 正常 bye 后重来
            except Exception as e:
                print(f"[runner] 连接断开: {e}；{backoff:.0f}s 后重连", file=sys.stderr)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_CAP)

    async def _run_once(self) -> None:
        token = self._credential()
        if not token:
            raise RuntimeError("缺少凭据：首次启动须 --token <pairing_token>")
        async with websockets.connect(
            self._ws_url(),
            subprotocols=[f"bearer.{token}"],
            max_size=16 * 1024 * 1024,
        ) as ws:
            await ws.send(json.dumps({
                "type": "hello",
                "data": {"os": self.os_type, "version": RUNNER_VERSION, "roots": [self.root]},
            }))
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                mtype = msg.get("type")
                data = msg.get("data") or {}
                if mtype == "paired":
                    self.device_key = str(data.get("device_key") or "")
                    _save_credentials({"server": self.server_url, "device_key": self.device_key})
                    print(f"[runner] 配对成功 device_id={data.get('device_id')}，凭据已存 {_CREDENTIALS_PATH}")
                elif mtype == "hello_ack":
                    print(f"[runner] 已连接云端 device_id={data.get('device_id')}，工作区根 {self.root}")
                elif mtype == "ping":
                    await ws.send(json.dumps({"type": "pong", "data": {}}))
                elif mtype == "call":
                    await self._handle_call(ws, data)
                elif mtype == "bye":
                    return
                # approval/未知类型：P0 只读工具无审批面，静默忽略

    async def _handle_call(self, ws, data: dict[str, Any]) -> None:
        call_id = str(data.get("call_id") or "")
        tool = str(data.get("tool") or "")
        args = data.get("args") or {}
        try:
            result = await execute_local(self.root, self.os_type, tool, args)
        except Exception as e:  # runner 侧任何崩溃都降级为错误回包，不让连接悬死
            result = {"ok": False, "error": f"runner 内部错误: {e}", "error_code": "RUNNER_INTERNAL"}
        await ws.send(json.dumps({"type": "result", "data": {"call_id": call_id, **result}}))
