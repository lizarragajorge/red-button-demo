import argparse

import uvicorn
from dotenv import load_dotenv

from .config import Settings


def main():
    parser = argparse.ArgumentParser(description="Run the Red Button Python API and built web app.")
    parser.add_argument("--reload", action="store_true", help="Reload local development code on changes.")
    args = parser.parse_args()
    load_dotenv()
    settings = Settings.from_env()
    if args.reload and settings.environment == "production":
        parser.error("--reload is only available outside production.")
    uvicorn.run(
        "server.main:app",
        host="0.0.0.0" if settings.environment == "production" else "127.0.0.1",
        port=settings.port,
        reload=args.reload,
        server_header=False,
    )


if __name__ == "__main__":
    main()
