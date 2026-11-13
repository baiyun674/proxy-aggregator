# -*- coding: utf-8 -*-
"""项目配置：订阅源 / 地区白名单 / 名额与超时。改这里即可，无需动 aggregator.py。"""

# ============ 1. 真实 GitHub 免费聚合订阅源（来自对话整理） ============
SUB_URLS = [
    # Au1rxx 聚合池（每小时 sing-box 实测真连接后发布，存活率高）
    "https://raw.githubusercontent.com/Au1rxx/free-vpn-subscriptions/main/output/clash.yaml",
    "https://raw.githubusercontent.com/Au1rxx/free-vpn-subscriptions/main/output/v2ray-base64.txt",
    # Zhuhai Free Nodes（每小时更新，约 50 精筛节点，含美/日/新/港/英/德）
    "https://raw.githubusercontent.com/zhuhaiuk/free-nodes/main/clash_config.yaml",
    # Pawdroid / Free-servers（近 20k star，每 6 小时更新，Base64 通用）
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
    # Ripaojiedian 永久免费池（每日更新，Clash YAML + Base64 双源）
    "https://raw.githubusercontent.com/ripaojiedian/freenode/main/clash",
    "https://raw.githubusercontent.com/ripaojiedian/freenode/main/sub",
    # aiboboxx V2Ray 免费池（长寿自动抓取，补 vmess/vless）
    "https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2",
    # V2RayAggregator 多源合并池（全网公开节点合并为 Clash）
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge_yaml.yml",

    # ===== 扩充源（按 star 高 + 每日更新筛选，2026-11 实测有效）=====
    # Barabama/FreeNodes（3.4k★，每日更新，双格式高产量：clash ~1.7k + uri ~3.6k）
    "https://raw.githubusercontent.com/Barabama/FreeNodes/refs/heads/main/nodes/clashmeta.yaml",
    "https://raw.githubusercontent.com/Barabama/FreeNodes/refs/heads/main/nodes/nodev2ray.txt",
    # ermaozi/get_subscribe（9.5k★，每日更新，聚合订阅 v2ray.txt ~580 + clash.yml ~219）
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/clash.yml",
    # chengaopan/AutoMergePublicNodes（8.4k★，每日更新，全网公开节点合并 Base64）
    "https://raw.githubusercontent.com/chengaopan/AutoMergePublicNodes/master/list.txt",
    # free18/v2ray（5.9k★，每日更新，Base64 通用订阅）
    "https://raw.githubusercontent.com/free18/v2ray/refs/heads/main/v.txt",
    # anaer/Sub（老牌长寿 Clash 池，~2.1k 节点）
    "https://raw.githubusercontent.com/anaer/Sub/main/clash.yaml",
    # 0xRadikal/Free-v2ray-Configs（844★，每日更新，v2rayNG profile Base64，量大）
    "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/verified/configs_base64.txt",

    # ===== 协议提纯大源（VLESS/Trojan/SS 快协议，提质用，2026 实测 URL 可达）=====
    # barry-far/V2ray-Config 按协议分流库：只抽快协议专库，避开大杂烩慢 vmess 池
    # vless.txt ~1.75MB（大量 VLESS-Reality）、trojan.txt ~152KB、ss.txt ~172KB
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/trojan.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/ss.txt",
    # TelegaVPN 专攻 VLESS-Reality/Hysteria2 精品池，Clash YAML ~56KB
    "https://raw.githubusercontent.com/TelegaVPN/free-vpn-keys/main/sub/clash/all.yaml",
]

# ============ 2. 常用国家与核心城市白名单 ============
TARGET_REGIONS = {
    "JP": {"name": "🇯🇵 日本", "cities": {"Tokyo": "🇯🇵 日本-东京", "Osaka": "🇯🇵 日本-大阪"},
           "keep_other_cities": False},
    "SG": {"name": "🇸🇬 新加坡", "cities": {"Singapore": "🇸🇬 新加坡"}, "keep_other_cities": True},
    "US": {"name": "🇺🇸 美国",
           "cities": {"Los Angeles": "🇺🇸 美国-洛杉矶", "San Jose": "🇺🇸 美国-圣何塞",
                      "Seattle": "🇺🇸 美国-西雅图", "Santa Clara": "🇺🇸 美国-硅谷",
                      "Silicon Valley": "🇺🇸 美国-硅谷", "New York": "🇺🇸 美国-纽约",
                      "Chicago": "🇺🇸 美国-芝加哥", "Dallas": "🇺🇸 美国-达拉斯",
                      "Atlanta": "🇺🇸 美国-亚特兰大", "Miami": "🇺🇸 美国-迈阿密",
                      "Ashburn": "🇺🇸 美国-阿什本"},
           "keep_other_cities": True},
    "HK": {"name": "🇭🇰 香港", "cities": {"Hong Kong": "🇭🇰 香港"}, "keep_other_cities": True},
    "TW": {"name": "🇹🇼 台湾", "cities": {"Taipei": "🇹🇼 台湾-台北"}, "keep_other_cities": False},
    "KR": {"name": "🇰🇷 韩国", "cities": {"Seoul": "🇰🇷 韩国-首尔"}, "keep_other_cities": False},
    "DE": {"name": "🇩🇪 德国", "cities": {"Frankfurt am Main": "🇩🇪 德国-法兰克福",
                                          "Frankfurt": "🇩🇪 德国-法兰克福"}, "keep_other_cities": True},
    "GB": {"name": "🇬🇧 英国", "cities": {"London": "🇬🇧 英国-伦敦"}, "keep_other_cities": True},
}

# 亚洲国家码（用于 server 侧 region_hint 判定，决定保底名额归属）
ASIAN_COUNTRY_CODES = {"HK", "TW", "JP", "KR", "SG", "MO", "TH", "VN", "MY", "ID", "PH", "IN", "CN"}

# 高风险/重度滥用机房 ASN 黑名单：
#   - HARD：真·蜜罐/重灾机房，命中直接淘汰（这些 IP 被各家风控重点标记，留下=白忙）
#   - SOFT：廉价数据中心，命中只「降权」不淘汰 —— 免费美国/欧洲节点绝大多数住在这几家，
#     若硬丢就会「一个西方 IP 都没有」，所以改为保留但排在干净节点后面。
BAD_ASN_KEYWORDS = ["m247", "sharktech"]
BAD_ASN_SOFT = ["colocrossing", "frantech", "buyvm", "psychz", "quadranet",
                "serverpoint", "chorus", "vultr", "digitalocean", "linode", "akamai"]
BAD_ASN_SOFT_PENALTY = 600    # 命中软黑名单的排序惩罚（ms），仍保留但排到后面

# 纯净度策略：
#   - BAD_ASN 命中 = 硬淘汰（真·重灾/蜜罐机房）
#   - ip-api 的 proxy 标志 = 节点出口本就是代理，几乎必然 True，默认只降权不淘汰
#     （设 DROP_ON_PROXY_FLAG=True 才硬丢，会大幅减少产量，一般别开）
#   - hosting（数据中心 IP）= 降权保留，原生 ISP 优先
DROP_ON_PROXY_FLAG = False
PROXY_PENALTY = 120         # 命中 proxy 标志的排序惩罚（ms）
HOSTING_PENALTY = 150       # 数据中心 IP 的排序惩罚（ms），原生 ISP 加 0

# ★明文 CDN 端口黑名单：挂在 Cloudflare 80 系明文端口上的 vmess/ss 节点，
#   通常被限速到 ~100KB/s 且晚高峰必炸，是「质量不高」的主要来源。
#   在送入隧道深测「之前」直接剔除，省下深测名额给快协议(443/Hy2/Reality)节点。
#   注意：只拉黑 CF 的明文(http)端口 80/8080/2052/2082/2086/2095；CF 的 https 端口
#   (443/8443/2053/2083/2087/2096) 不在名单内，那是 trojan/vless-over-cdn 的正常端口。
DROP_PLAINTEXT_CDN_PORTS = True
PLAINTEXT_CDN_PORTS = (80, 8080, 2052, 2082, 2086, 2095)

# ============ 3. 测速 / 深测参数 ============
TCP_TIMEOUT = 2.0           # TCP 握手初筛超时（秒）
TUNNEL_TIMEOUT = 8.0        # 真连接隧道探测超时（秒）——放宽，给慢的免费节点机会
MAX_VERIFY_NODES = 1000     # 每次送入隧道深测的最大节点数（隧道通过率仅 ~10%，收录数≈名额×0.1；450→1000 让收录翻倍。public 仓库分钟数不限量，可放心加深）
ASIA_MIN_RATIO = 0.55       # ★亚洲保底：深测名额中至少切给 server 侧亚洲节点的比例
BASE_LISTENER_PORT = 20000  # 临时 Mihomo 隧道监听起始端口
CONCURRENCY_PING = 80       # TCP 初筛并发
CONCURRENCY_TUNNEL = 80     # 隧道深测并发（名额放大到 1000，并发同步提，控制单次时长）

# ip-api 纯净度查询字段
GEOIP_FIELDS = "status,query,countryCode,city,isp,as,proxy,hosting"
OUTPUT_FILE = "mihomo_stable.yaml"
SINGBOX_OUTPUT_FILE = "singbox.json"

# 是否除「fallback 固定IP」外，额外为每个城市生成一组「url-test 防抖优选」（仅 Mihomo）
ENABLE_URLTEST_GROUPS = True
URLTEST_TOLERANCE = 500     # 仅当新节点快 500ms 以上才允许切 IP（防抖）
URLTEST_INTERVAL = 600      # 10 分钟测一次

# ★健康检查 URL：必须用「墙外、被墙」的端点。test-url 是走代理节点出去访问的，
#   只有节点真能翻出去才连得上 → 这才是「验真梯子」。绝不能用国内可达站点，
#   否则只能连国内的废节点会假装通过。google 被墙最彻底，generate_204 返回快。
HEALTHCHECK_URL = "http://www.google.com/generate_204"
URLTEST_URL = HEALTHCHECK_URL
