"""Local launcher. Only binds loopback; existing analyzer API remains compatible."""

import os, threading, webbrowser
from runtime import startup

if __name__ == "__main__":
    workspace_lock = startup()
    from app import app

    port = int(os.environ.get("IFMS_PORT", "5000"))
    if os.environ.get("IFMS_OPEN_BROWSER", "1") == "1":
        threading.Timer(
            1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/suite/")
        ).start()
    app.run(host="127.0.0.1", port=port, debug=False)
