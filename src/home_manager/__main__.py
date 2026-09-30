import argparse
import logging
from pathlib import Path
import secrets
import sys

import uvicorn

from .app.api import create_app


def main():
    if sys.argv[1:2] == ["gpu-host"]:  # The family GPU relay: a separate process (models/gpu_host.py).
        from .models.gpu_host import main as gpu_host
        gpu_host(sys.argv[2:])
        return
    if sys.argv[1:2] == ["check-ledger"]:  # Read-only ledger health report (app/ledger_check.py).
        from .app.ledger_check import main as check_ledger
        sys.exit(check_ledger(sys.argv[2:]))
    if sys.argv[1:2] == ["index-documents"]:  # Rebuild the full-text index of document text (app/index_documents.py).
        from .app.index_documents import main as index_documents
        sys.exit(index_documents(sys.argv[2:]))
    parser = argparse.ArgumentParser(description="Run the local Home Manager document capture UI. "
                                                 "Run `home-manager gpu-host --help` to share this computer's GPU with family members, "
                                                 "`home-manager check-ledger` to check each profile's ledger for broken money rules, "
                                                 "or `home-manager index-documents --rebuild` to rebuild the search index of document text.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--control-dir", type=Path, help="Settings location; default is %%LOCALAPPDATA%%/HomeManager on Windows.")
    parser.add_argument("--install-laya", action="store_true", help="Download the pinned Laya checkpoint once (about 850 MB), then exit.")
    args = parser.parse_args()
    from .app.manager import default_control_dir
    if args.install_laya:
        from .models.laya_runtime import install
        print("Laya installed at", install((args.control_dir or default_control_dir()) / "models" / "laya"))
        return
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535.")
    from .core.logs import configure
    log_file = configure(args.control_dir or default_control_dir())
    logging.getLogger("home_manager").info("starting port=%s", args.port)
    token = secrets.token_urlsafe(32)
    print(f"\nOpen this private session link in your browser:\nhttp://127.0.0.1:{args.port}/#token={token}\n"
          f"Diagnostic log: {log_file}\n", flush=True)
    uvicorn.run(create_app(args.control_dir, token, args.port), host="127.0.0.1", port=args.port,
                access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
