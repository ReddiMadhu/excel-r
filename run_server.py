"""
Entry point for the Excel Rationalization Server.

Usage:
    python run_server.py
    python run_server.py --host 0.0.0.0 --port 8000
"""
import argparse
import os
import sys

# Add the project root to path so imports work
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def main():
    parser = argparse.ArgumentParser(description="Excel Rationalization Server")
    parser.add_argument(
        "--host",
        default=os.getenv("SERVER_HOST", "0.0.0.0"),
        help="Host to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("SERVER_PORT", "8000")),
        help="Port to listen on (default: 8000)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(
        "src.server.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
