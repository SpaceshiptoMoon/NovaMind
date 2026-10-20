"""novamind-runner 命令行入口。

用法（设计文档 §2.1 配对流程）：

    # 首次配对（token 从 Web 设置页生成，10 分钟有效）
    python -m novamind.runner join --server http://localhost:8100 --token <pairing_token> --root D:/projects

    # 后续重连（凭据已持久化，无需 token）
    python -m novamind.runner join --server http://localhost:8100 --root D:/projects
"""
import argparse
import asyncio

from novamind.runner.client import RunnerClient


def main() -> None:
    parser = argparse.ArgumentParser(prog="novamind-runner", description="NovaMind 伴生 runner（哑执行器）")
    sub = parser.add_subparsers(dest="command", required=True)
    join = sub.add_parser("join", help="连接云端并进入工作循环")
    join.add_argument("--server", required=True, help="云端地址，如 http://localhost:8100")
    join.add_argument("--token", default=None, help="配对凭证（仅首次需要；之后用持久化 device_key）")
    join.add_argument("--root", required=True, help="授权工作区根目录（绝对路径）")
    args = parser.parse_args()

    client = RunnerClient(server_url=args.server, pairing_token=args.token, root=args.root)
    try:
        asyncio.run(client.run_forever())
    except KeyboardInterrupt:
        print("\n[runner] 已退出")


if __name__ == "__main__":
    main()
