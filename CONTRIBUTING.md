# 贡献指南

感谢你愿意参与！这个项目最需要的是 **不同型号/固件的路由器适配反馈**。

---

## 🐛 报 Bug 前先做这些

**1. 确认基础信息**

```bash
python --version                    # 需要 3.10+
pip show python-xiaomi-miwifi       # 版本
```

**2. 手动验证路由器管理页面**

打开 `http://<路由器IP>/cgi-bin/luci/web`，查看网页源码，确认有这两行：

```javascript
var newEncryptMode = parseInt('0' 或 '1')     ← 决定 SHA1 还是 SHA256
key: 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
deviceId = 'xx:xx:xx:xx:xx:xx'
```

**如果你的路由器没有这两行** —— 那可能是全新的固件体系，请在 issue 里贴出页面源码片段。

**3. 记录错误响应的原文**

登录失败时路由器会返回 JSON，**原文照抄**：

| 响应 | 含义 |
|---|---|
| `{"code":401,"msg":"not auth"}` | 密码或算法错 |
| `{"code":401,"msg":"Invalid token"}` | 请求格式错 |
| 其它 | 贴原文 |

---

## 📋 报 Issue 时请附上

```markdown
**路由器型号**：小米/红米 XXX（如 RP02、AX3000T、BE6500）
**固件版本**：（管理页面「系统状态」里看，或 `init_info` 的 romversion）
**newEncryptMode**：0 或 1
**Python 版本**：3.11.x
**复现步骤**：
**完整错误信息**：（原文，别改写）
```

> ⚠️ **不要贴你的密码、公网 IP、宽带账号**。贴 key / deviceId 时打码后 4 位。

---

## 🛠️ 开发环境

```bash
git clone https://github.com/2670321532/miwifi-mcp.git
cd miwifi-mcp
pip install -r requirements.txt
pip install ruff          # 可选，用于 lint

cp config.example.json config.local.json
# 编辑 config.local.json，填入你的路由器地址和后台密码
```

**验证能跑通**：

```bash
# 1. 静态检查（不连路由器）
python tests/smoke_test.py
python tests/mcp_handshake_test.py

# 2. 真连路由器（手动，CI 不跑）
MIWIFI_PASSWORD=你的密码 python -c "
import asyncio, server
async def m():
    c = server.get_client()
    print(await c.async_get_led())
asyncio.run(m())
"
```

---

## 📐 代码规范

用 **ruff**（配置在 `pyproject.toml`）：

```bash
ruff check server.py          # lint
ruff check --fix server.py    # 自动修
ruff format server.py         # 格式化
```

**提交前必须**：
```bash
ruff check server.py && python -m py_compile server.py && python tests/smoke_test.py
```

主要约定：
- 行宽 **110**（由 formatter 管，不用手数）
- 双引号、4 空格缩进、LF 换行（`.editorconfig` 已配，编辑器会自动遵守）
- 工具函数必须有**中文 docstring**（AI 客户端会把它当工具描述展示给模型）
- **工具名统一 `miwifi_` 前缀**

---

## ➕ 新增工具的步骤

**1. 先确认真实端点和返回结构**

```bash
# 登录拿 stok 后（参考 server.py 的 async_login）
curl "http://192.168.31.1/cgi-bin/luci/;stok=<stok>/api/xqsystem/your_endpoint"
```

> ⚠️ **不要靠猜端点名**。本项目已发现 `python-xiaomi-miwifi` 库里的
> `api/xqnetwork/portforward` 在 RP02 固件上是 **404**，正确的是 `api/xqsystem/portforward`。
> **实测过再写代码**。

**2. 加工具函数**

```python
@mcp.tool()
async def miwifi_your_feature() -> str:
    """一句话中文说明（会展示给 AI 模型，说清用途和返回什么）"""
    c = get_client()
    return _summarize(await c.async_get_xxx())
```

**3. 加进 `tests/smoke_test.py` 的 `EXPECTED_TOOLS`**

CI 会校验工具清单，新增工具必须同步更新，否则测试失败。

---

## 🔒 安全红线（PR 会被直接拒）

1. **不加 `shutdown`** —— 远程执行后必须物理拔插电源，且全家断网
2. **不加 `reset`（恢复出厂）**
3. **不加改密码功能**
4. **不在代码里硬编码任何真实密码 / 内网 IP / MAC / 宽带账号**
5. **不把 `config.local.json` 提交进去**（已 gitignore，但别 `git add -f`）
6. **日志里不打印密码**（PPPoE 的 `password` 字段必须脱敏）

---

## 📝 提交 PR

**提交信息**（中文或英文都行，参考现有风格）：

```
feat: 支持 AX3000T 的 SHA256 登录
fix: 修正 RP02 上 portforward 端点 404
docs: 补充排错章节
test: 为 dhcp 绑定加冒烟测试
```

**PR 描述里请写**：
- 在哪个型号/固件上验证过
- 怎么验证的（贴关键输出）
- 会不会影响现有功能

**CI 必须全绿**（lint + 3 个 Python 版本的 smoke + MCP 握手）。

---

## 🙏 特别欢迎的贡献

| 类型 | 说明 |
|---|---|
| **新型号适配** | 尤其 `newEncryptMode = 0`（SHA1）的老固件 |
| **端点修正** | 发现某固件端点 404 时，补上正确路径 |
| **工具补充** | WiFi 改名/改密码（需用户显式确认）、访客网络、端口限速等 |
| **文档** | 排错案例、型号兼容性表 |

---

## 许可

提交的代码按 [MIT](LICENSE) 授权。
