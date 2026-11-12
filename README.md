# Proxy Aggregator · GitHub 免费节点聚合 + 真落地校验 + 亚洲保底

整合对话里讨论成熟的「节点聚合池」方案，做成一个可直接 fork 即用、跑在 **GitHub Actions** 上的全自动流水线。

## 它解决什么

1. 多个 GitHub 免费节点分享项目互相扒、重复率高、80% 是死节点、名字还造假（挂着「东京」其实是 Cloudflare 美国反代）。
2. 直接用 url-test / load-balance 会让出口 IP 每隔几分钟乱跳 → 调用 AI 接口、登录固定账号时触发风控。
3. **（本项目新增）GitHub Actions 免费 runner 默认在美国**，TCP 测速天然偏袒美国节点，会把深测名额 `MAX_VERIFY_NODES` 全占满，导致**亚洲节点根本没机会被深测就被淘汰**。

## 流水线（7 步）

| 步 | 模块 | 作用 |
|----|------|------|
| 1 | `fetch_subscriptions` | 拉 14 个真实订阅源（Clash YAML / Base64 / 明文 URI / v2rayNG profile） |
| 2 | `parse_uri` | vmess / vless / trojan / ss / hysteria2 → Mihomo 字典，按 `server:port` 去重 |
| 3 | `tcp_ping` | 高并发异步 TCP 握手初筛死活，解析出真实 server IP（`_tcp_ip`）与延迟 |
| 4 | `pre_tag_region` + `select_candidates_with_asia_quota` | **★亚洲保底**：对 server IP 做轻量 GeoIP 标 region_hint，深测名额先按比例(默认 0.55)切一块保底给亚洲候选，剩余按全局延迟填充 |
| 5 | `verify_exit_and_purity` | 拉起临时 Mihomo 隧道，逐节点穿透取**真实出口 exit_ip** 与 rtt |
| 6 | `ip-api` 纯净度核验 | 按 exit_ip 查国家/城市 + `proxy`/`hosting`/ASN 黑名单，剔除脏 IP（m247/buyvm/sharktech 等） |
| 7 | `build_mihomo_config` | 每个核心城市生成 `fallback` 组，**死锁第一个可用纯净 IP，断线才顺延**，永不乱跳；另附一组 `url-test` 防抖优选（tolerance 500 / 10min 测一次） |
| 8 | `build_singbox_config` | 同步导出 **sing-box JSON**：每城一个 `selector`(手动锁IP) + 一个 `urltest`(防抖)，含 mixed 入站、DoH DNS、CN 直连路由 |

## 两种输出口

| 输出 | 文件 | 适用客户端 | 锁定方式 |
|------|------|-----------|---------|
| Mihomo (Clash Meta) | `mihomo_stable.yaml` | Clash Verge Rev / Flclash / NekoBox | `fallback`(🔒 死锁) + `url-test`(⚡ 防抖) |
| sing-box | `singbox.json` | sing-box / NekoBox / Hiddify | `selector`(🔒 手动固定) + `urltest`(⚡ 防抖) |

> sing-box 的 `selector` 一旦选定某节点就不自动跳，等价「锁 IP」意图；`urltest` 对应「防抖优选」。`ASIA_MIN_RATIO` / 白名单等对两种输出共用同一份 `config.py`。sing-box 端无 `tolerance` 字段，防抖用 `interval` + `interrupt_connect_latency` 近似。

## 亚洲保底效果（真实数据实测）

用 6 个真实源聚合 400 个存活节点、深测名额压到 40 时：

```
纯全局延迟排序：  亚洲节点入深测 = 12
加入亚洲保底后：  亚洲节点入深测 = 22   (↑ 近 2 倍)
```

自测（不联网）里极端场景 500 美国 + 80 亚洲、名额 250：纯排序亚洲 **0** 入选，加保底 **80** 全进。

> 入口 IP≠出口 IP 的纯中转节点少数会漏标；但绝大多数 vmess/vless/trojan/ss/hy2 免费节点是单跳直连，server IP 即落地，故用 server IP 做「入围保底」是合理近似，最终国家/城市仍由 exit_ip 真连接核验兜底。

## 本地跑

```bash
# 联网全流程（隧道深测需要本地有 mihomo 核心）
pip install -r requirements.txt
python aggregator.py            # 同时生成 mihomo_stable.yaml 与 singbox.json

# 离线自检核心逻辑（无需网络、无需 mihomo）
python selftest.py              # 或 DRY_RUN=1 python aggregator.py
```

## 部署到 GitHub Actions（推荐）

1. 新建仓库，把本目录整体推上去（含 `.github/workflows/build.yml`）。
2. 仓库 Settings → Actions → General → Workflow permissions 选 **Read and write**（脚本要 push `output` 分支）。
3. 到 Actions 页面手动 Run workflow 一次验证；之后每 1.5 小时自动把最新产物推到 **`output` 分支**（`main` 永远是干净源码，本地 push 不再需要 rebase）。
4. **Clash Verge 订阅（Public 仓库 + GitHub Pages，已自动化）**
   1. 仓库需为 **Public**（本仓库无任何密钥，公开不泄露敏感信息；且 public 仓库 Actions 分钟数不限量，1.5h 高频刷新才跑得动）。
   2. workflow 已含「启用 GitHub Pages」步骤：首次运行会自动把 Pages 源设为 `output` 分支（无需手动去 Settings 点）。若 API 权限被仓库级 Workflow permissions 限制，手动兜底：Settings → Pages → Source 选 **Deploy from a branch** → Branch 选 `output` / `root` → Save。
   3. 在 Clash Verge Rev 订阅里粘贴（把用户名/仓库名换成你的）：
      `https://baiyun674.github.io/proxy-aggregator/mihomo_stable.yaml`
      一键订阅、自动更新（Verge 按自己的更新周期重新拉，workflow 每 1.5h 刷新内容；首次启用 Pages 后等 1~2 分钟构建完成才可访问）。
   - 保持 Private 时：Pages 免费版不可用，改用「本地文件导入」——从 Actions 每次运行的 Artifact 或带 token 的 raw 下载 `mihomo_stable.yaml`，在 Verge 里以 Local 方式导入（缺点：不能自动更新）。

## 配置（全在 `config.py`）

| 变量 | 含义 | 默认 |
|------|------|------|
| `SUB_URLS` | 订阅源列表，自己加 Raw 链接 | 14 个真实源（高星+日更筛选） |
| `TARGET_REGIONS` | 国家/核心城市白名单 + 是否保留该国其它城市 | JP/SG/US/HK/TW/KR/DE/GB |
| `ASIAN_COUNTRY_CODES` | 判定「亚洲保底」归属的国家码 | HK/TW/JP/KR/SG/TH/… |
| `MAX_VERIFY_NODES` | 每轮深测上限（控 ip-api 免费额度） | 450 |
| `ASIA_MIN_RATIO` | ★深测名额里保底给亚洲节点的比例 | 0.55 |
| `BAD_ASN_KEYWORDS` | 脏机房/滥用 ASN 黑名单关键词 | m247/buyvm/… |
| `TCP_TIMEOUT / TUNNEL_TIMEOUT` | 初筛 / 真连接超时（秒） | 2.0 / 6.0 |

> 亚洲节点偏少时：把 `ASIA_MIN_RATIO` 调高（如 0.7），或把 `MAX_VERIFY_NODES` 调到 450（亚洲候选池会更大）。

## 安全须知

免费节点部分是被扫出来的公网肉鸡/蜜罐：全程强制 `fake-ip` + DoH 防 DNS 劫持；**绝不**走 `http://` 明文站、不用高价值金融/主力邮箱账号。TLS 流量出口只能看到域名，看不到具体账号密码。

## 文件结构

```
proxy-aggregator/
├── aggregator.py            # 主管线（解析→初筛→亚洲保底→隧道深测→纯净度→生成 Mihomo + sing-box）
├── config.py                # 全部可配置项 + 真实订阅源（含 ASIA_MIN_RATIO / ENABLE_URLTEST_GROUPS）
├── selftest.py              # 离线自检（DRY_RUN）
├── requirements.txt         # aiohttp / PyYAML
└── .github/workflows/build.yml   # 每 1.5h 自动跑，产物推到独立 output 分支并自动启用 Pages（含 .nojekyll）
```
