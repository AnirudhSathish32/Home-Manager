import argparse
from pathlib import Path
import secrets

import uvicorn

from .api import create_app


def main():
    parser = argparse.ArgumentParser(description="Run the local Home Manager document capture UI.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--control-dir", type=Path, help="Settings location; default is %%LOCALAPPDATA%%/HomeManager on Windows.")
    parser.add_argument("--install-laya", action="store_true", help="Download the pinned Laya checkpoint once (about 850 MB), then exit.")
    args = parser.parse_args()
    if args.install_laya:
        from .laya_runtime import install
        from .manager import default_control_dir
        print("Laya installed at", install((args.control_dir or default_control_dir()) / "models" / "laya"))
        return
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535.")
    token = secrets.token_urlsafe(32)
    print(f"\nOpen this private session link in your browser:\nhttp://127.0.0.1:{args.port}/#token={token}\n", flush=True)
    uvicorn.run(create_app(args.control_dir, token, args.port), host="127.0.0.1", port=args.port,
                access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
