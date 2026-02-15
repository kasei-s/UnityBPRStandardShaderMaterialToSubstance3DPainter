# Tools/SubstancePainter/lib_remote.py
# Minimal Remote Scripting client for Substance 3D Painter (run.json).
# Painter must be started with --enable-remote-scripting.
import base64
import json
import urllib.request

class RemotePainter:
    def __init__(self, host="localhost", port=60041):
        self.base = f"http://{host}:{port}"

    def _post(self, path, payload: dict, timeout=60):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.read().decode("utf-8", errors="replace")

    def checkConnection(self):
        return self._post("/run.json", {"js": ""}, timeout=5)

    def execScript(self, code: str, lang: str = "python", timeout=300):
        b64 = base64.b64encode(code.encode("utf-8")).decode("ascii")
        lang = lang.lower()
        if lang == "python":
            return self._post("/run.json", {"python": b64}, timeout=timeout)
        if lang == "js":
            return self._post("/run.json", {"js": b64}, timeout=timeout)
        raise ValueError("lang must be 'python' or 'js'")
