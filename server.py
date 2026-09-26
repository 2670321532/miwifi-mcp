"""
小米路由器 MCP Server（RP02 / 固件 1.0.46 / newEncryptMode=1）

基于 python-xiaomi-miwifi 库，但覆盖了登录实现：
  - 原库用 SHA1 → 本机固件要求 SHA256（newEncryptMode=1）
  - 请求体必须 form-data（不是 JSON）

范围（用户确认）：
  读：设备列表 / IPv6 / PPPoE / 端口转发列表 / DHCP 列表 / 带宽 / 拓扑 / WiFi 详情 / LED / 黑名单
  写：增删端口转发 / DHCP 静态绑定 / 拉黑设备 / 开关 LED
  动作：reboot
  ❌ 排除：shutdown / reset / 改密码
"""

import hashlib
import json
import logging
import os
import random
import re
import time
from typing import Any

import aiohttp
from mcp.server.fastmcp import FastMCP
from xiaomi_miwifi import ClientDevice, MiWiFiClient

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("miwifi-mcp")

# ── 配置来源（优先级：环境变量 > 同目录 config.local.json > 默认值）──
_CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.local.json")
_cfg = {}
if os.path.exists(_CFG_FILE):
    try:
        with open(_CFG_FILE, encoding="utf-8") as f:
            _cfg = json.load(f)
    except Exception as _e:
        log.warning("读取 %s 失败: %s", _CFG_FILE, _e)

ROUTER_HOST = os.environ.get("MIWIFI_HOST") or _cfg.get("host") or "192.168.31.1"
ROUTER_PASSWORD = os.environ.get("MIWIFI_PASSWORD") or _cfg.get("password") or ""
ROUTER_USER = os.environ.get("MIWIFI_USER") or _cfg.get("user") or "admin"


class RP02Client(MiWiFiClient):
    """覆盖登录：适配 newEncryptMode=1（SHA256 + form-data）"""

    async def async_login(self) -> str:
        session = await self._ensure_session()
        base = f"http://{self._host}:{self._port}/cgi-bin/luci"
        timeout = aiohttp.ClientTimeout(total=20)

        async with session.get(f"{base}/web", timeout=timeout) as resp:
            page = await resp.text()

        m_key = re.search(r"key\s*:\s*'([^']+)'", page)
        m_dev = re.search(r"deviceId\s*=\s*'([^']+)'", page)
        m_mode = re.search(r"newEncryptMode\s*=\s*parseInt\('(\d)'\)", page)
        if not m_key:
            raise RuntimeError("login key not found on web page")
        key = m_key.group(1)
        dev = m_dev.group(1) if m_dev else "0"
        new_mode = m_mode.group(1) if m_mode else "0"

        nonce = "0_%s_%d_%d" % (dev, int(time.time()), random.randint(0, 9999))

        if new_mode == "1":
            inner = hashlib.sha256((self._password + key).encode()).hexdigest()
            pwd = hashlib.sha256((nonce + inner).encode()).hexdigest()
        else:
            inner = hashlib.sha1((self._password + key).encode()).hexdigest()
            pwd = hashlib.sha1((nonce + inner).encode()).hexdigest()

        body = f"username={self._username}&password={pwd}&logtype=2&nonce={nonce}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0",
            "Referer": f"{base}/web",
        }
        async with session.post(f"{base}/api/xqsystem/login", data=body,
                                headers=headers, timeout=timeout) as resp:
            text = await resp.text()

        try:
            j = json.loads(text)
        except json.JSONDecodeError as err:
            raise RuntimeError(f"login: bad JSON response: {text[:200]}") from err

        if j.get("code") != 0 or not j.get("token"):
            raise RuntimeError(f"login failed: {j}")
        self._token = j["token"]
        return self._token


mcp = FastMCP("miwifi")
_client: RP02Client | None = None


def get_client() -> RP02Client:
    global _client
    if _client is None:
        if not ROUTER_PASSWORD:
            raise RuntimeError("请设置环境变量 MIWIFI_PASSWORD")
        _client = RP02Client(host=ROUTER_HOST, password=ROUTER_PASSWORD,
                             username=ROUTER_USER)
    return _client


def _summarize(obj: Any, limit: int = 30) -> str:
    """把大对象压成可读文本"""
    if isinstance(obj, list):
        items = []
        for x in obj[:limit]:
            if isinstance(x, dict):
                items.append(dict(list(x.items())[:8]))
            else:
                items.append(x)
        return json.dumps(items, ensure_ascii=False, indent=1, default=str)
    if isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False, indent=1, default=str)[:4000]
    return str(obj)


# ══════════════════════ 读：网络与状态 ══════════════════════

@mcp.tool()
async def miwifi_clients() -> str:
    """列出当前连在路由器上的所有设备（谁在用网、IP、MAC、上下行速度）"""
    c = get_client()
    devs = await c.async_get_clients()
    out = []
    for d in devs:
        if isinstance(d, ClientDevice):
            out.append({
                "name": getattr(d, "name", ""),
                "mac": getattr(d, "mac", ""),
                "ip": getattr(d, "ip", ""),
                "online": getattr(d, "online", None),
                "upload_speed": getattr(d, "upload_speed", None),
                "download_speed": getattr(d, "download_speed", None),
                "upload_total": getattr(d, "upload_total", None),
                "download_total": getattr(d, "download_total", None),
                "parent": getattr(d, "parent", ""),
                "band": getattr(d, "band", ""),
                "signal": getattr(d, "signal", None),
                "is_router": getattr(d, "is_router", None),
            })
        else:
            out.append(d if isinstance(d, dict) else str(d))
    return "在线设备 %d 台：\n%s" % (len(out), json.dumps(out, ensure_ascii=False, indent=1, default=str)[:6000])


@mcp.tool()
async def miwifi_system_info() -> str:
    """路由器系统信息（型号、固件版本、运行状态、WAN/LAN 概况）"""
    c = get_client()
    r = {}
    for name, fn in [("init_info", c.async_get_init_info),
                     ("status", c.async_get_newstatus),
                     ("lan", c.async_get_lan_info),
                     ("wan", c.async_get_wan_info)]:
        try:
            r[name] = await fn()
        except Exception as e:
            r[name] = f"ERR: {str(e)[:100]}"
    return _summarize(r)


@mcp.tool()
async def miwifi_ipv6() -> str:
    """IPv6 状态（是否开启、地址、前缀、连接方式）"""
    c = get_client()
    return _summarize(await c.async_get_ipv6_status())


@mcp.tool()
async def miwifi_pppoe() -> str:
    """PPPoE 拨号状态（是否在线、IP、网关、DNS、连接时长）。
    注意：路由器返回的原始数据里含宽带账号明文密码，此处已脱敏。"""
    c = get_client()
    r = await c.async_get_pppoe_status()
    if isinstance(r, dict) and r.get("password"):
        r = dict(r)
        r["password"] = "<已脱敏>"
    return _summarize(r)


@mcp.tool()
async def miwifi_bandwidth() -> str:
    """带宽使用历史（实时上下行、累计流量）"""
    c = get_client()
    r = {}
    for name, fn in [("history", c.async_get_bandwidth_history),
                     ("wan_stats", c.async_get_wan_statistics)]:
        try:
            r[name] = await fn()
        except Exception as e:
            r[name] = f"ERR: {str(e)[:100]}"
    return _summarize(r)


@mcp.tool()
async def miwifi_topology() -> str:
    """网络拓扑（Mesh 节点、子设备连接关系）"""
    c = get_client()
    return _summarize(await c.async_get_topology())


@mcp.tool()
async def miwifi_wifi_detail() -> str:
    """WiFi 详情（2.4G/5G 信道、频宽、功率、SSID、密码是否隐藏等）"""
    c = get_client()
    r = {}
    for name, fn in [("wifi", c.async_get_wifi_detail),
                     ("channels_24g", lambda: c.async_get_available_channels(0)),
                     ("channels_5g", lambda: c.async_get_available_channels(1))]:
        try:
            r[name] = await fn()
        except Exception as e:
            r[name] = f"ERR: {str(e)[:100]}"
    return _summarize(r)


# ══════════════════════ 读：安全与转发 ══════════════════════

@mcp.tool()
async def miwifi_port_forward_list() -> str:
    """端口转发规则列表。
    注意：本固件（RP02 1.0.46）的正确端点是 api/xqsystem/portforward，
    库默认的 api/xqnetwork/portforward 在此固件返回 404。"""
    c = get_client()
    for ep in ("api/xqsystem/portforward", "api/xqnetwork/portforward?ftype=1"):
        try:
            r = await c.async_luci_request(ep)
            if isinstance(r, dict) and r.get("code") == 0:
                lst = r.get("list") or []
                if not lst:
                    return f"当前没有端口转发规则（端点 {ep} 返回空列表）"
                return "%d 条端口转发规则（端点 %s）：\n%s" % (
                    len(lst), ep, _summarize(lst))
        except Exception as e:
            str(e)[:120]
            continue
    return "❌ 未能读取端口转发列表（试过的端点都失败）"


@mcp.tool()
async def miwifi_dhcp_reservations() -> str:
    """DHCP 静态地址绑定列表"""
    c = get_client()
    return _summarize(await c.async_get_dhcp_reservations())


@mcp.tool()
async def miwifi_lan_dhcp() -> str:
    """LAN / DHCP 服务配置（地址池、网关、租期）"""
    c = get_client()
    return _summarize(await c.async_get_lan_dhcp())


@mcp.tool()
async def miwifi_blocked_devices() -> str:
    """黑名单设备列表"""
    c = get_client()
    r = {}
    for name, fn in [("blocked", c.async_get_blocked_devices),
                     ("macfilter", c.async_get_macfilter),
                     ("dmz", c.async_get_dmz),
                     ("qos", c.async_get_qos_info)]:
        try:
            r[name] = await fn()
        except Exception as e:
            r[name] = f"ERR: {str(e)[:100]}"
    return _summarize(r)


@mcp.tool()
async def miwifi_led() -> str:
    """路由器 LED 灯状态"""
    c = get_client()
    return _summarize(await c.async_get_led())


# ══════════════════════ 写：需要谨慎的操作 ══════════════════════

@mcp.tool()
async def miwifi_add_port_forward(ip: str, name: str, proto: int,
                                  sport: int, dport: int) -> str:
    """添加端口转发规则。
    ip=内网目标IP  name=规则名  proto=1(TCP)/2(UDP)  sport=外网端口  dport=内网端口"""
    c = get_client()
    ok = await c.async_add_port_forward(ip=ip, name=name, proto=proto,
                                        sport=sport, dport=dport)
    return "✅ 已添加端口转发 %s:%d → %s:%d (%s)" % (
        "公网", sport, ip, dport, "TCP" if proto == 1 else "UDP") if ok else "❌ 添加失败"


@mcp.tool()
async def miwifi_delete_port_forward(sport: int) -> str:
    """删除端口转发规则（按外网端口号定位）"""
    c = get_client()
    ok = await c.async_delete_port_forward(sport=sport)
    return "✅ 已删除外网端口 %d 的转发规则" % sport if ok else "❌ 删除失败"


@mcp.tool()
async def miwifi_add_dhcp_reservation(mac: str, ip: str, name: str) -> str:
    """添加 DHCP 静态地址绑定（固定设备 IP）"""
    c = get_client()
    ok = await c.async_add_dhcp_reservation(mac=mac, ip=ip, name=name)
    return f"✅ 已绑定 {mac} → {ip} ({name})" if ok else "❌ 绑定失败"


@mcp.tool()
async def miwifi_remove_dhcp_reservation(mac: str) -> str:
    """删除 DHCP 静态绑定"""
    c = get_client()
    ok = await c.async_remove_dhcp_reservation(mac=mac)
    return f"✅ 已解除 {mac} 的静态绑定" if ok else "❌ 解除失败"


@mcp.tool()
async def miwifi_block_device(mac: str) -> str:
    """拉黑设备（禁止上网）。⚠️ 传设备 MAC"""
    c = get_client()
    ok = await c.async_block_device(mac=mac)
    return f"✅ 已拉黑 {mac}" if ok else "❌ 拉黑失败"


@mcp.tool()
async def miwifi_reboot() -> str:
    """⚠️ 重启路由器（断网 十几秒~1分钟，之后自动恢复）。
    仅在网络异常需要远程重启时使用。"""
    c = get_client()
    await c.async_reboot()
    return "🔄 重启命令已发送。路由器将在十几秒后断开，约 1 分钟后恢复。"


# ══════════════════════ 逃生口（只读，方便排查）══════════════════════

@mcp.tool()
async def miwifi_luci_get(path: str) -> str:
    """只读 LuCI 透传：直接 GET 任意 API 路径（如 api/misystem/messages）。
    出于安全，禁止 reboot/reset/set_/upgrade 等修改类路径。"""
    # 库内部已有只读黑名单（reboot/set_/upgrade/bind 等），这里再加一层
    blocked = ("reboot", "reset", "shutdown", "upgrade", "delete", "remove")
    if any(b in path.lower() for b in blocked):
        return f"❌ 该路径不在只读白名单内（被安全策略拦截）：{path}"
    c = get_client()
    r = await c.async_luci_request(path)
    return _summarize(r)


# ⚠️ 已知端点差异（本固件 RP02 1.0.46 实测）
#   api/xqnetwork/portforward  → 404（库默认路径，此固件不存在）
#   api/xqsystem/portforward   → 200 ✅（正确路径）
#   其余库方法（clients / ipv6 / pppoe / led / dhcp / wifi / blocked）均实测可用


if __name__ == "__main__":
    if not ROUTER_PASSWORD:
        print("⚠️  未设置 MIWIFI_PASSWORD 环境变量")
    mcp.run()
