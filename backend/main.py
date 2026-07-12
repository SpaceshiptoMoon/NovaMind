# main.py
"""
应用入口
支持通过 --config 参数指定配置环境
"""
import argparse
import uvicorn
import sys
import os

_BACKEND_SRC = os.path.join(os.path.dirname(__file__), "src")
if _BACKEND_SRC not in sys.path:
    sys.path.insert(0, _BACKEND_SRC)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="智能知识库系统后端")
    parser.add_argument(
        "--config", "-c",
        type=str,
        default="development",
        help="配置环境名称，对应 yaml/{name}.yaml 文件（默认: development）"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="服务监听地址（默认: 0.0.0.0）"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8100,
        help="服务监听端口（默认: 8100）"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="启用热重载（开发模式）"
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=1,
        help="工作进程数（默认: 1）"
    )
    return parser.parse_args()


def create_app():
    """
    创建应用实例（供 uvicorn factory 使用）

    Returns:
        FastAPI: 应用实例
    """
    from novamind.core.middleware.app_factory import create_app as _create_app
    return _create_app()



def main():
    """主函数"""
    args = parse_args()

    # 设置环境变量，供 YAML 配置加载器读取
    os.environ["ENVIRONMENT"] = args.config

    # 预加载配置以验证
    from novamind.setting.yaml_config import get_config
    try:
        config = get_config()
        print(f"已加载配置: {config.environment}")

        print(f"向量数据库: {config.vector_db.type}")
        print(f"数据库: {config.database.host}:{config.database.port}/{config.database.database}")
    except Exception as e:
        print(f"配置加载失败: {e}")
        sys.exit(1)

    # 统一使用 uvicorn factory 模式
    workers = args.workers
    if args.reload and workers > 1:
        print(f"警告: 热重载模式下 workers 参数被忽略，固定为 1")
        workers = 1

    uvicorn.run(
        "main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=workers,
    )
 

if __name__ == "__main__":
    main()
