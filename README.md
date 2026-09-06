# CloudBlaze Keep-Alive · ddos-guard 自动绕过保活

对 CloudBlaze（Pterodactyl 白标面板）托管的服务器实例做**自动保活**：定时探测在线状态，实例离线时自动拉起。
内置**纯 Python 实现的 ddos-guard 防护绕过**（PoW 挑战 + 浏览器指纹提交），无需浏览器、无需 Selenium、零第三方依赖。

> CloudBlaze = panel.cloudblaze.org，Pterodactyl 白标面板，后端套了 ddos-guard 反爬/反机器人。
> 本项目已在该面板上实测通过（FREE-MOSCOW 节点，Intel Xeon E3-1270 v6）。

---

## ⚡ 推荐在 VPS 上跑

本项目**推荐部署在 VPS（云服务器）上长期运行**，纯 Python 标准库实现，**资源占用极低**，7×24 挂机毫无压力：

| 指标 | 实测占用 |
|---|---|
| 内存（RSS） | ≈ **25 MB**（运行瞬间峰值，跑完即释放） |
| CPU | **近乎为 0**（每 5 分钟跑一次，单次执行 < 0.1 秒） |
| 磁盘 | **< 1 MB**（不含日志） |
| 依赖 | **0 个**（仅 Python 3.8+ 标准库） |

> 运行方式：cron 每 5 分钟执行一次 `keepalive.py`，**跑完即退出，不留常驻进程**，对 VPS 完全无感。

**User-Agent 示例**（绕过 ddos-guard 挑战时使用，必须 Firefox 系 UA，否则即使挑战通过也会被拦）：

```
Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0
```

---

## 功能特性

| 功能 | 说明 |
|---|---|
| 🛡️ ddos-guard 自动绕过 | 遇到 403 挑战页自动解 PoW + 指纹验证，cookies 持久化（有效期约 1 年） |
| 🔄 离线自动拉起 | 探测到 `offline` 自动发送 `start` 信号 |
| ⚡ 在线跳过 | 实例 `running` 时不重复操作 |
| 🚨 suspend 告警 | 实例被 suspend 时跳过并 Telegram 通知（需人工处理） |
| 📱 Telegram 通知（可选） | 拉起成功 / 失败 / 探测异常推送 |
| 🐍 零依赖 | 仅 Python 标准库（urllib / hashlib / json / ssl） |

## 文件说明

```
cloudblaze_api.py   # API 客户端：自动过挑战 + 调用 Pterodactyl Client API
ddg_solver.py       # ddos-guard 挑战独立演示脚本（解一次挑战并保存 cookies）
keepalive.py        # 保活主逻辑（探测 + 拉起 + Telegram 通知），供 cron 调用
apitoken.example    # API Key 配置模板（复制为 .apitoken）
server_id.example   # 服务器 UUID 配置模板（复制为 server_id）
```

---

## 🛡️ ddos-guard 是怎么绕过的

CloudBlaze 面板对所有请求先过 [DDoS-Guard](https://ddos-guard.net/) 防护：没有通过挑战的请求会收到 **403 挑战页**，页面里内嵌一段 JS：

```js
window.__BPC = {sid:'...', non:'...', dif:1, ts:...};
```

浏览器执行 JS 后会把 **指纹 + PoW 结果** POST 到 `/__bp_verify`，服务端验证通过后下发 `__bp_verified` / `__bp_session` / `__ddg8_` cookies。之后带这些 cookies 访问，全部放行。

本项目用纯 Python 复现了这个过程：

1. **请求 API** → 收到 403 挑战页；
2. **解析挑战参数**：从 `window.__BPC` 正则提取 `sid`、`non`、`dif`；
3. **构造浏览器指纹 payload**（30+ 字段，模拟真实 Firefox 环境）：
   - `sw/sh/aw/ah` 屏幕与可用分辨率、`cd` 色深、`pr` 像素比
   - `cf`（canvas 指纹）、`af`（AudioContext 指纹）、`ff`（字体指纹）
   - `wr`（WebGL 渲染器：`ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 ...)`）、`wv`（WebGL 厂商）
   - `pl/tz/to/ln` 平台与时区（Asia/Shanghai, UTC-8）
4. **计算指纹提交值**（字段顺序**固定**，错一个顺序就对不上）：

   ```
   fpCommit = sha256(cf | wv | wr | ff | af | pl | tz | sw | sh | cd | hc)
   ```

5. **解 PoW**：暴力找 `n`，使

   ```
   sha256(f"{sid}:{non}:{fpCommit}:{n}")  以 dif 个 '0' 开头
   ```

   `dif=1` 时平均 16 次可找到；`dif` 越大越耗时；
6. **提交验证**：POST `/__bp_verify`，带 JSON payload + `pow` + `pn`，成功返回 `{"status":"ok"}`；
7. **保存 cookies** 到 `cookies_server.txt`（绑定当前请求出口 IP，有效期约 1 年）；
8. 之后所有请求带 `Cookie` + `Authorization: Bearer <API Key>`，全部通过；
9. **cookie 失效** → 再次遇到 403 → `cloudblaze_api.py` 自动重新解挑战并重试（全程幂等，无感）。

### 几个关键坑（血泪教训）

- **User-Agent 必须用 Firefox 系**，否则即使挑战通过也会被拦：

  ```
  Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0
  ```

- **指纹字段顺序固定**：`order = [cf, wv, wr, ff, af, pl, tz, sw, sh, cd, hc]`，join 后做 sha256，顺序不能乱；
- **新版 Pterodactyl Client API 的服务器列表在 `GET /api/client`**（`/api/client/servers` 会 404，旧文档路径）；
- cookies **绑定 IP**：在浏览器里手动过挑战后导出的 cookies 不能直接用于服务器，必须让服务器自己解一次挑战；
- 面板对频繁请求会临时限流（偶发 `RemoteDisconnected`），脚本里留了重试与间隔。

---

## 🚀 快速开始

### 1. 获取 API Key（只需要这个，不需要 SSH）

直接打开 **https://panel.cloudblaze.org/api** 创建 API Key：

1. **Allowed IPs 填运行脚本的服务器公网出口 IP**（Key 绑定 IP，填错用不了）；
2. 创建后密钥**只显示一次**，立即复制；
3. 写入文件（注意文件名以 `.` 开头）：

   ```bash
   echo '你的_API_KEY' > /root/cloudblaze/.apitoken
   chmod 600 /root/cloudblaze/.apitoken
   ```

### 2. 获取服务器 UUID

面板 URL 形如 `https://panel.cloudblaze.org/server/<uuid>`，或者运行：

```bash
python3 cloudblaze_api.py status   # 会列出你账号下的所有服务器和 UUID
```

写入：

```bash
echo '你的_服务器UUID' > /root/cloudblaze/server_id
```

### 3. 测试

```bash
python3 cloudblaze_api.py status    # 查看服务器列表与运行状态
python3 keepalive.py                # 手动跑一次保活（离线会自动拉起）
```

### 4. 挂 cron（每 5 分钟）

```cron
*/5 * * * * /usr/bin/python3 /root/cloudblaze/keepalive.py >> /root/cloudblaze/keepalive-cron.log 2>&1
```

> 路径自定义时，可用环境变量 `CB_HOME` 指定配置目录：
> `CB_HOME=/path/to/conf python3 cloudblaze_api.py status`

### 5.（可选）Telegram 通知

在 `keepalive.py` 中填写：

```python
TG_API_KEY=[REDACTED]
TG_CHAT_ID = '你的_Telegram_用户ID'
```

---

## 🤔 API Key 和服务器（Limbo / MC）的区别

很多朋友刚接触会把 **API Key** 和 **服务器实例** 搞混，这里一次性说清楚：

| 概念 | 是什么 | 干什么用的 |
|---|---|---|
| **API Key** | 面板账号下生成的**客户端令牌**（Client API Token） | 调用面板 API 管理"服务器实例"：查状态、发 `start/stop/restart` 信号、看资源占用。**属于控制平面** |
| **服务器实例** | 面板里创建的一个"游戏服务器"，里面跑的是 | 实际运行的游戏服务。**属于数据平面** |

服务器实例里跑的东西可以是：

- **Limbo（如 NanoLimbo）**：极轻量的 Minecraft 占位服务器（纯 Java，几乎不占资源），常用于连接测试、防掉落、防宕机、保号占位；
- **MC（如 Paper / Spigot / Vanilla）**：完整的 Minecraft 服务端，承载真实玩法。

**核心区别（3 句话）：**

1. **保活只需要 API Key** —— 不需要 SSH 进服务器、不需要实例控制台权限；API Key 是面板层面"遥控器"；
2. **不管实例里跑的是 Limbo 还是 MC，保活逻辑完全一样** —— 我们操作的是"实例"这个整体（`power start` 信号），与内部装什么无关；
3. **API Key 决定"你能不能控制这个实例"，Limbo/MC 决定"实例启动后跑什么"** —— 一个 API Key 可以控制该账号下的所有实例，而 Limbo/MC 只是实例里的程序。

> 简单记忆：**API Key = 面板的钥匙**，**Limbo/MC = 房间里的家具**。本项目的保活，就是拿着钥匙定期去看看房间里有没有断电，断电了就重新开灯。

---

## 🙏 致谢

本项目参考并感谢以下项目/作者：

- [DDoS-Guard](https://ddos-guard.net/) — 防护服务商官方站点
- [NanoLimbo](https://github.com/Nan1t/NanoLimbo) — 轻量 Limbo 服务器实现（保活对象的典型场景）

## ⚠️ 免责声明

本项目**仅用于学习交流与自动化运维自己合法拥有的服务器**。请勿用于：
- 绕过付费防护、滥用他人资源；
- 攻击或干扰 ddos-guard 保护的任何服务；
- 违反面板服务条款的行为。

使用前请确认你的操作符合面板 ToS 与当地法律。作者不对任何滥用行为负责。

## 📄 License

[MIT](LICENSE)
