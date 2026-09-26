# miwifi-mcp

**小米 / 红米路由器 MCP Server** —— 让 AI 助手（Claude Desktop、Reasonix、Cursor 等支持 MCP 的客户端）直接管理你的小米路由器。

> Xiaomi / Redmi router MCP server — manage your router from any MCP-capable AI assistant.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

---

## ✨ 功能

**读（只读查询）**

| 工具 | 说明 |
|---|---|
| `miwifi_clients` | 列出所有在线设备（名称 / IP / MAC / 上下行速度 / 累计流量）|
| `miwifi_system_info` | 型号、固件、运行状态、WAN / LAN 概况 |
| `miwifi_ipv6` | IPv6 状态（模式、地址、前缀、DNS）|
| `miwifi_pppoe` | PPPoE 拨号状态（**密码自动脱敏**）|
| `miwifi_bandwidth` | 带宽历史 / WAN 统计 |
| `miwifi_topology` | 网络拓扑（Mesh 节点、连接关系）|
| `miwifi_wifi_detail` | WiFi 详情（信道、频宽、功率、SSID）+ 可用信道 |
| `miwifi_port_forward_list` | 端口转发规则列表 |
| `miwifi_dhcp_reservations` | DHCP 静态绑定列表 |
| `miwifi_lan_dhcp` | LAN / DHCP 服务配置 |
| `miwifi_blocked_devices` | 黑名单 / MAC 过滤 / DMZ / QoS |
| `miwifi_led` | 路由器 LED 灯状态 |

**写（会改变路由器状态）**

| 工具 | 说明 |
|---|---|
| `miwifi_add_port_forward` | 添加端口转发 |
| `miwifi_delete_port_forward` | 删除端口转发 |
| `miwifi_add_dhcp_reservation` | 添加 DHCP 静态绑定 |
| `miwifi_remove_dhcp_reservation` | 删除 DHCP 静态绑定 |
| `miwifi_block_device` | 拉黑设备（禁止上网）|
| `miwifi_reboot` | 重启路由器（断网十几秒后自动恢复）|

**逃生口**

| 工具 | 说明 |
|---|---|
| `miwifi_luci_get` | 只读透传任意 LuCI API 路径（内置黑名单拦截 `reboot` / `set_` / `upgrade` / `delete` 等修改类路径）|

**❌ 故意不提供**

- `shutdown` —— 远程执行后**必须物理拔插电源**才能重启，断网自毁
- `reset` —— 恢复出厂设置
- 修改管理密码

---

## 📦 安装

```bash
git clone https://github.com/<your-name>/miwifi-mcp.git
cd miwifi-mcp
pip install -r requirements.txt
```

> 国内建议加 pip 镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple`

## ⚙️ 配置

复制模板并填入你的信息：

```bash
cp config.example.json config.local.json
```

```json
{
  "host": "192.168.31.1",
  "user": "admin",
  "password": "你的路由器后台管理密码"
}
```

**优先级**：环境变量 > `config.local.json` > 内置默认值

| 环境变量 | 对应字段 |
|---|---|
| `MIWIFI_HOST` | `host` |
| `MIWIFI_USER` | `user` |
| `MIWIFI_PASSWORD` | `password` |

> `config.local.json` **不要提交到 Git**（已在 `.gitignore` 中）。

## 🔌 接入 MCP 客户端

**Claude Desktop**（`claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "miwifi": {
      "command": "python",
      "args": ["/absolute/path/to/miwifi-mcp/server.py"]
    }
  }
}
```

**Reasonix**（`config.toml`）：

```toml
[[plugins]]
  name = "miwifi"
  command = "python"
  args = ["/absolute/path/to/miwifi-mcp/server.py"]
```

重启客户端即可看到 `miwifi_*` 工具。

---

## 🔑 登录算法（重点）

小米路由器的登录是 **challenge-response**，而且**新旧固件算法不同**。
本项目的实现基于对路由器管理页面 JS 的逆向，**已适配两种模式**：

```javascript
// 路由器页面里决定用哪种算法的变量
var newEncryptMode = parseInt('1')   // 1 → SHA256，0 → SHA1

nonce = [0, deviceId, 时间戳, 随机数].join('_')   // deviceId = 路由器 MAC（带冒号）

// newEncryptMode == 1
password = SHA256( nonce + SHA256(明文密码 + key) )
// newEncryptMode == 0
password = SHA1( nonce + SHA1(明文密码 + key) )
```

其中 `key` 从管理页面抓取（每个固件可能不同），然后：

```
POST /cgi-bin/luci/api/xqsystem/login
Content-Type: application/x-www-form-urlencoded      ← ⚠️ 必须是 form-data，不能用 JSON
body: username=admin&password=<hash>&logtype=2&nonce=<nonce>
```

成功返回 `{"code":0,"token":"<stok>"}`，之后所有请求带上：

```
GET /cgi-bin/luci/;stok=<token>/<api路径>
```

### ⚠️ 错误响应速判

| 响应 | 含义 |
|---|---|
| `{"code":401,"msg":"not auth"}` | 请求格式对，但**密码或算法错** |
| `{"code":401,"msg":"Invalid token"}` | **请求格式错**（连验证都没进，通常是用了 JSON 而非 form-data）|
| `{"code":0,"token":"..."}` | ✅ 成功 |

> **登录速率限制：连续 4 次失败会被临时锁定**，请勿盲目重试。

### 📌 端点差异

部分固件改了 API 路径，本项目已做兼容：

| 端点 | 结果 |
|---|---|
| `api/xqnetwork/portforward` | ❌ 404（部分固件不存在）|
| `api/xqsystem/portforward` | ✅ 200 |

---

## 🧪 实测环境

| 项 | 值 |
|---|---|
| 路由器 | 小米路由器 **RP02** |
| 固件 | **1.0.46** |
| 加密模式 | `newEncryptMode = 1`（SHA256）|
| 特性 | Wi-Fi 7（MLO）、2.5G 网口 |
| Python | 3.11 |

**理论兼容**：所有使用 LuCI HTTP API 的小米 / 红米路由器（本项目会自动识别 `newEncryptMode`）。
如果你的型号不行，欢迎提 issue 附上固件版本和错误响应。

---

## 🔒 安全说明

1. **密码只存本地** —— `config.local.json`（已 gitignore）或环境变量；代码里不含任何凭据
2. **只读优先** —— `miwifi_luci_get` 有黑名单，无法通过它触发修改操作
3. **不提供危险操作** —— `shutdown` / `reset` / 改密码被刻意排除
4. **PPPoE 密码脱敏** —— 路由器原始返回的宽带账号密码会被替换为 `<已脱敏>`
5. **建议** —— 路由器后台密码**不要与其他服务共用**

## 🛠️ 排错

**`login key not found on web page`**
→ 路由器管理页面结构不同。手动访问 `http://<路由器IP>/cgi-bin/luci/web`，
查看源码里是否有 `key: '...'` 和 `deviceId = '...'`。

**`login failed: {'code': 401, 'msg': 'not auth'}`**
→ 密码错，或固件的加密模式判断有误。确认 `newEncryptMode` 的值。

**`login failed: {'code': 401, 'msg': 'Invalid token'}`**
→ 请求不是 form-data。检查 `Content-Type`。

**工具返回 404 / `bad JSON`**
→ 该固件的端点路径不同，用 `miwifi_luci_get` 试探正确路径。

---

## 📄 License

[MIT](LICENSE)

## 🙏 致谢

- [`python-xiaomi-miwifi`](https://pypi.org/project/python-xiaomi-miwifi/) —— 提供了 LuCI API 的封装与端点映射
- [Model Context Protocol](https://modelcontextprotocol.io/) —— MCP 协议与 SDK

> 本项目与小米公司无关联，为第三方非官方工具。使用风险自负。
