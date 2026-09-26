"""
MCP 协议握手测试：启动 server.py 子进程，走标准 MCP stdio 流程。

验证：
  1. initialize 能拿到 serverInfo
  2. notifications/initialized 被接受
  3. tools/list 返回预期的工具集合与 schema

⚠️ 不调用任何真实工具（那些需要连上路由器）。
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server.py"

EXPECTED_TOOL_COUNT_MIN = 18


def main() -> int:
    env = dict(os.environ)
    env["MIWIFI_PASSWORD"] = env.get("MIWIFI_PASSWORD", "dummy-for-test")
    env["MIWIFI_HOST"] = env.get("MIWIFI_HOST", "192.168.31.1")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        env=env, cwd=str(ROOT),
    )

    def send(obj):
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def recv(req_id, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == req_id:
                return msg
        return None

    try:
        print("=" * 60)
        print("MCP 协议握手测试")
        print("=" * 60)

        # ── 1. initialize ──
        send({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ci-smoke", "version": "1.0"},
            },
        })
        r = recv(1, 60)
        if not r:
            print("❌ initialize 无响应")
            print("stderr:", proc.stderr.read()[:800])
            return 1
        if r.get("error"):
            print("❌ initialize 返回 error:", r["error"])
            return 1
        res = r.get("result") or {}
        info = res.get("serverInfo") or {}
        print(f"[1/3] initialize          OK  serverInfo={json.dumps(info, ensure_ascii=False)}")
        assert info.get("name"), "serverInfo.name 缺失"

        # ── 2. initialized 通知 ──
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        time.sleep(0.3)
        print("[2/3] notifications/initialized  OK")

        # ── 3. tools/list ──
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        r = recv(2, 30)
        if not r:
            print("❌ tools/list 无响应")
            return 1
        tools = ((r.get("result") or {}).get("tools")) or []
        print("[3/3] tools/list          OK  %d 个工具" % len(tools))

        if len(tools) < EXPECTED_TOOL_COUNT_MIN:
            print("❌ 工具数不足：%d < %d" % (len(tools), EXPECTED_TOOL_COUNT_MIN))
            return 1

        # 每个工具必须有 name / description / inputSchema
        for t in tools:
            assert t.get("name"), f"工具缺 name: {t}"
            assert t.get("description"), "工具 {} 缺 description".format(t["name"])
            assert "inputSchema" in t, "工具 {} 缺 inputSchema".format(t["name"])

        names = sorted(t["name"] for t in tools)
        print()
        print("工具清单：")
        for n in names:
            print(f"   - {n}")

        # 危险工具检查
        for bad in ("shutdown", "reset"):
            if any(bad in n for n in names):
                print(f"❌ 检测到危险工具关键词 {bad!r} 被注册")
                return 1

        print()
        print("=" * 60)
        print("✅ MCP 握手全部通过")
        print("=" * 60)
        return 0

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
