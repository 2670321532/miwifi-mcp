"""
Smoke test：验证 server.py 能被导入、MCP 工具全部注册。

不连接真实路由器 —— 只做静态检查，可在 CI 无网络环境下运行。
需要 Python 3.11+（依赖 python-xiaomi-miwifi 的要求）。
"""

import importlib.util
import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server.py"

# 提供假密码，避免导入时因缺少配置报错
os.environ.setdefault("MIWIFI_PASSWORD", "dummy-for-test")
os.environ.setdefault("MIWIFI_HOST", "192.168.31.1")

EXPECTED_TOOLS = [
    # 读
    "miwifi_clients",
    "miwifi_system_info",
    "miwifi_ipv6",
    "miwifi_pppoe",
    "miwifi_bandwidth",
    "miwifi_topology",
    "miwifi_wifi_detail",
    "miwifi_port_forward_list",
    "miwifi_dhcp_reservations",
    "miwifi_lan_dhcp",
    "miwifi_blocked_devices",
    "miwifi_led",
    # 写
    "miwifi_add_port_forward",
    "miwifi_delete_port_forward",
    "miwifi_add_dhcp_reservation",
    "miwifi_remove_dhcp_reservation",
    "miwifi_block_device",
    "miwifi_reboot",
    # 逃生口
    "miwifi_luci_get",
]

# 恶意/危险工具绝不能被注册
FORBIDDEN_TOOLS = [
    "miwifi_shutdown",
    "miwifi_reset",
    "miwifi_change_password",
    "miwifi_set_password",
]


def load_server():
    spec = importlib.util.spec_from_file_location("miwifi_server", SERVER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {SERVER}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["miwifi_server"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    print("=" * 60)
    print("miwifi-mcp smoke test")
    print("=" * 60)

    assert SERVER.exists(), f"server.py 不存在：{SERVER}"
    print("[1/4] server.py 存在                     OK")

    mod = load_server()
    print("[2/4] 导入成功                           OK")

    # 找出所有 miwifi_ 前缀的函数
    found = sorted(
        name for name, obj in inspect.getmembers(mod, inspect.isfunction)
        if name.startswith("miwifi_")
    )
    print("[3/4] 发现 %d 个 miwifi_* 函数" % len(found))

    missing = [t for t in EXPECTED_TOOLS if t not in found]
    if missing:
        print(f"      ❌ 缺少工具：{missing}")
        return 1

    extra = [t for t in found if t not in EXPECTED_TOOLS]
    if extra:
        print(f"      ⚠️  多出未预期的工具：{extra}")

    leaked = [t for t in FORBIDDEN_TOOLS if t in found]
    if leaked:
        print(f"      ❌ 危险工具被注册了：{leaked}")
        return 1
    print("      ✅ 预期工具齐全（%d 个）" % len(EXPECTED_TOOLS))
    print("      ✅ 危险工具未注册（shutdown/reset/改密码）")

    # 检查 MCP 实例
    mcp_obj = getattr(mod, "mcp", None)
    assert mcp_obj is not None, "未找到 mcp 实例"
    print("[4/4] MCP 实例存在                       OK")

    # 检查配置读取逻辑（不真连）
    assert hasattr(mod, "ROUTER_HOST"), "缺少 ROUTER_HOST"
    assert hasattr(mod, "ROUTER_PASSWORD"), "缺少 ROUTER_PASSWORD"
    assert mod.ROUTER_HOST == "192.168.31.1", "ROUTER_HOST 环境变量未生效"

    print()
    print("=" * 60)
    print("✅ 全部通过")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
