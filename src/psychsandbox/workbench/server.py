"""科研 Web 工作台本地运行启动入口

默认监听 127.0.0.1:8000。
遵守安全约束：仅监听本地回环地址，不输出密钥，浏览器不持有模型密钥。
"""
from __future__ import annotations

import argparse
from pathlib import Path
from dotenv import load_dotenv
import uvicorn
from .api import create_app

# 优先加载项目根目录下的 .env 配置
env_path = Path(__file__).resolve().parents[3] / ".env"
if env_path.exists():
    load_dotenv(env_path)


def main():
    parser = argparse.ArgumentParser(description="PsychSandbox Scientific Workbench Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable reload")
    args = parser.parse_args()

    app = create_app()
    print(f"==================================================")
    print(f"科研 Web 工作台服务已启动: http://{args.host}:{args.port}")
    print(f"模式: 本地科研单机模式 (监听: {args.host})")
    print(f"==================================================")

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
