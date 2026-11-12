#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub 免费节点聚合 + 真落地校验 + IP 纯净度过滤 + 亚洲节点保底
=================================================================
整合对话中的「增强版」流水线，并补上最后一项约定：
  优先保底筛选亚洲节点，防止 GitHub Actions 美国 runner 的 TCP 测速
  偏袒美国节点、把 MAX_VERIFY_NODES 名额全部占满、饿死亚洲节点。

流程：
  1. 拉取多个 GitHub 免费订阅源（Clash YAML / Base64 / 明文 URI）
  2. 解析 vmess/vless/trojan/ss/hysteria2 -> Mihomo 字典，按 server:port 去重
  3. TCP 握手初筛存活，顺便解析出真实 server IP 并缓存（_tcp_ip / _tcp_ms）
  4. 【亚洲保底】对存活的 server IP 做一次轻量 GeoIP，标记 region_hint；
     深测名额 MAX_VERIFY_NODES 先切出一块固定比例给亚洲候选，
     剩余名额再按全局延迟填充，确保亚洲节点永远进得了深测。
  5. 拉起临时 Mihomo 隧道，逐节点穿透拿到真实出站 exit_ip 与 rtt。
  6. 批量核验 exit_ip 的国家/城市 + 纯净度（proxy/hosting/ASN 黑名单）。
  7. 按城市分组生成「锁定单一稳定纯净 IP」的 fallback Mihomo 配置。

可配置项集中在 config.py；离线自检：DRY_RUN=1 python aggregator.py
"""
import asyncio
import aiohttp
import yaml
import base64
import json
import urllib.parse
import socket
import time
import subprocess
import os
from typing import List, Dict, Any, Tuple

from config import (
    SUB_URLS, TARGET_REGIONS, ASIAN_COUNTRY_CODES, BAD_ASN_KEYWORDS,
    TCP_TIMEOUT, TUNNEL_TIMEOUT, MAX_VERIFY_NODES, ASIA_MIN_RATIO,
    BASE_LISTENER_PORT, CONCURRENCY_PING, CONCURRENCY_TUNNEL,
    GEOIP_FIELDS, OUTPUT_FILE, SINGBOX_OUTPUT_FILE,
    ENABLE_URLTEST_GROUPS, URLTEST_TOLERANCE, URLTEST_INTERVAL, URLTEST_URL,
    DROP_ON_PROXY_FLAG, PROXY_PENALTY, HOSTING_PENALTY,
)


# ================= 1. 解码 / 解析 =================
def safe_b64decode(s: str) -> str:
    s = s.strip()
    n = len(s) % 4
    if n:
        s += "=" * (4 - n)
    try:
        return base64.urlsafe_b64decode(s).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def parse_uri(uri: str) -> Dict[str, Any]:
    """把常见明文分享链接转成 Mihomo (Clash Meta) 字典格式。"""
    uri = uri.strip()
    try:
        if uri.startswith("vmess://"):
            data = json.loads(safe_b64decode(uri[8:]))
            node = {
                "name": "vmess", "type": "vmess",
                "server": data["add"], "port": int(data["port"]),
                "uuid": data["id"], "alterId": int(data.get("aid", 0)),
                "cipher": data.get("scy", "auto"), "udp": True,
            }
            if data.get("tls") == "tls":
                node["tls"] = True
                if data.get("sni"):
                    node["servername"] = data["sni"]
            if data.get("net") == "ws":
                node["network"] = "ws"
                node["ws-opts"] = {
                    "path": data.get("path", "/"),
                    "headers": {"Host": data.get("host", data["add"])},
                }
            return node

        elif uri.startswith(("vless://", "trojan://", "hy2://", "hysteria2://")):
            parsed = urllib.parse.urlparse(uri)
            scheme = "hysteria2" if parsed.scheme in ("hy2", "hysteria2") else parsed.scheme
            params = urllib.parse.parse_qs(parsed.query)
            node = {"name": urllib.parse.unquote(parsed.fragment) or scheme, "type": scheme,
                    "server": parsed.hostname, "port": int(parsed.port), "udp": True}
            if scheme == "vless":
                node["uuid"] = parsed.username
                node["tls"] = params.get("security", [""])[0] in ("tls", "reality")
                if "sni" in params: node["servername"] = params["sni"][0]
                if "fp" in params: node["client-fingerprint"] = params["fp"][0]
                if "flow" in params: node["flow"] = params["flow"][0]
                if params.get("security", [""])[0] == "reality":
                    node["reality-opts"] = {
                        "public-key": params.get("pbk", [""])[0],
                        "short-id": params.get("sid", [""])[0],
                    }
                if params.get("type", ["tcp"])[0] in ("ws", "grpc"):
                    node["network"] = params["type"][0]
            elif scheme == "trojan":
                node["password"] = parsed.username
                node["tls"] = True
                if "sni" in params: node["servername"] = params["sni"][0]
            elif scheme == "hysteria2":
                node["password"] = parsed.username
                if "sni" in params: node["sni"] = params["sni"][0]
                if params.get("insecure", ["0"])[0] == "1":
                    node["skip-cert-verify"] = True
            return node

        elif uri.startswith("ss://"):
            body = uri[5:].split("#")[0]
            if "@" in body:
                userinfo, hostport = body.split("@", 1)
                userinfo = safe_b64decode(userinfo)
            else:
                userinfo, hostport = safe_b64decode(body).rsplit("@", 1)
            cipher, password = userinfo.split(":", 1)
            server, port = hostport.rsplit(":", 1)
            return {"name": "ss", "type": "ss", "server": server,
                    "port": int(port.split("/")[0].split("?")[0]),
                    "cipher": cipher, "password": password, "udp": True}
    except Exception:
        pass
    return {}


# ================= 2. 拉取订阅 =================
async def fetch_subscriptions(urls: List[str]) -> List[Dict[str, Any]]:
    raw_nodes: List[Dict[str, Any]] = []
    async with aiohttp.ClientSession() as session:
        for url in urls:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()
                    if "proxies:" in text:
                        data = yaml.safe_load(text)
                        if isinstance(data, dict) and "proxies" in data:
                            raw_nodes.extend(data["proxies"])
                            continue
                    decoded = safe_b64decode(text) if "://" not in text[:30] else text
                    for line in decoded.splitlines():
                        node = parse_uri(line)
                        if node:
                            raw_nodes.append(node)
            except Exception as e:
                print(f"[!] 拉取失败 {url}: {e}")

    unique: Dict[str, Dict[str, Any]] = {}
    for n in raw_nodes:
        s, p = n.get("server"), n.get("port")
        if s and p and s not in ("127.0.0.1", "localhost"):
            unique[f"{s}:{p}"] = n
    print(f"[*] 抓取完成：共 {len(raw_nodes)} 个节点，去重后 {len(unique)} 个。")
    return list(unique.values())


# ================= 3. TCP 初筛（记录解析后的 server IP） =================
async def tcp_ping(node: Dict[str, Any], sem: asyncio.Semaphore) -> Dict[str, Any]:
    async with sem:
        server, port = str(node["server"]), int(node["port"])
        loop = asyncio.get_running_loop()
        try:
            t0 = time.perf_counter()
            addr = await loop.getaddrinfo(server, port, family=socket.AF_INET, type=socket.SOCK_STREAM)
            real_ip = addr[0][4][0]
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(real_ip, port), timeout=TCP_TIMEOUT)
            node["_tcp_ip"] = real_ip
            node["_tcp_ms"] = int((time.perf_counter() - t0) * 1000)
            writer.close()
            await writer.wait_closed()
            return node
        except Exception:
            return {}


# ================= 4. 轻量 GeoIP：给 server IP 打 region_hint =================
async def ipapi_batch(session, ips: List[str], fields: str) -> Dict[str, Dict[str, Any]]:
    """ip-api 免费批量接口，每批 100 个，遵守速率限制。"""
    out: Dict[str, Dict[str, Any]] = {}
    ips = [ip for ip in dict.fromkeys(ips) if ip]
    for i in range(0, len(ips), 100):
        batch = ips[i:i + 100]
        payload = [{"query": ip, "fields": fields} for ip in batch]
        try:
            async with session.post("http://ip-api.com/batch", json=payload,
                                    timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 200:
                    for item in await resp.json():
                        if item.get("status") == "success":
                            out[item["query"]] = item
        except Exception as e:
            print(f"[!] GeoIP 批量查询异常: {e}")
        if i + 100 < len(ips):
            await asyncio.sleep(1.5)
    return out


def classify_region(cc: str, city: str) -> str:
    """根据 server IP 国家/城市粗分区域，用于亚洲保底名额。"""
    if cc in ASIAN_COUNTRY_CODES:
        return "asia"
    if cc in ("US", "CA", "MX"):
        return "america"
    if cc in ("DE", "GB", "FR", "NL", "IT", "ES", "SE", "RU", "PL", "AT", "BE", "CH"):
        return "europe"
    return "other"


async def pre_tag_region(nodes: List[Dict[str, Any]]) -> None:
    ips = [n.get("_tcp_ip") for n in nodes if n.get("_tcp_ip")]
    async with aiohttp.ClientSession() as session:
        info = await ipapi_batch(session, ips, "status,query,countryCode,city")
    tagged = 0
    for n in nodes:
        rec = info.get(n.get("_tcp_ip"))
        if rec:
            n["_hint_region"] = classify_region(rec.get("countryCode"), rec.get("city", ""))
            tagged += 1
        else:
            n["_hint_region"] = "unknown"
    asia = sum(1 for n in nodes if n.get("_hint_region") == "asia")
    print(f"[*] region_hint 标注完成 {tagged}/{len(nodes)}，其中 server 侧疑似亚洲节点 {asia} 个。")


# ================= 5. 亚洲保底名额选择 =================
def select_candidates_with_asia_quota(alive: List[Dict[str, Any]],
                                      quota: int, asia_min_ratio: float) -> List[Dict[str, Any]]:
    """
    把深测名额先按比例(asia_min_ratio)保底给 server 侧标注为 asia 的节点，
    剩下的名额再从全局延迟排序池补足。这样美国 runner 的 TCP 偏袒不会饿死亚洲。
    """
    asia = sorted([n for n in alive if n.get("_hint_region") == "asia"], key=lambda x: x["_tcp_ms"])
    others = sorted([n for n in alive if n.get("_hint_region") != "asia"], key=lambda x: x["_tcp_ms"])

    asia_slots = min(len(asia), int(quota * asia_min_ratio))
    picked_asia = asia[:asia_slots]
    remaining = quota - len(picked_asia)
    picked_rest = others[:remaining]

    # 若亚洲候选不足 asia_slots，把空出的名额回填给 others（按延迟）
    if len(picked_asia) < asia_slots:
        borrow = asia_slots - len(picked_asia)
        picked_rest = others[:remaining + borrow]

    chosen = picked_asia + picked_rest
    print(f"[*] 深测名额分配：保底亚洲 {len(picked_asia)} + 其他 {len(picked_rest)} "
          f"= {len(chosen)} / 上限 {quota}（asia 候选池 {len(asia)}，others 池 {len(others)}）。")
    return chosen


# ================= 6. Mihomo 隧道深测 =================
def _resolve_mihomo_bin() -> str:
    for c in ("./mihomo", "mihomo", "./mihomo.exe"):
        if os.path.exists(c) or c == "mihomo":
            return c
    return "mihomo"


async def probe_node_via_tunnel(node: Dict[str, Any], local_port: int, sem: asyncio.Semaphore) -> Dict[str, Any]:
    proxy_url = f"http://127.0.0.1:{local_port}"
    trace_url = "http://api.ipify.org?format=json"
    async with sem:
        try:
            t0 = time.perf_counter()
            async with aiohttp.ClientSession() as session:
                async with session.get(trace_url, proxy=proxy_url,
                                       timeout=aiohttp.ClientTimeout(total=TUNNEL_TIMEOUT)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        node["_exit_ip"] = data.get("ip")
                        node["_rtt_ms"] = int((time.perf_counter() - t0) * 1000)
                        return node
        except Exception:
            pass
    return {}


async def verify_exit_and_purity(alive: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    candidates = select_candidates_with_asia_quota(alive, MAX_VERIFY_NODES, ASIA_MIN_RATIO)
    if not candidates:
        return {}

    temp_proxies, listeners = [], []
    for idx, node in enumerate(candidates):
        p = {k: v for k, v in node.items() if not k.startswith("_")}
        p["name"] = f"node_{idx}"
        temp_proxies.append(p)
        listeners.append({"name": f"in_{idx}", "type": "mixed",
                          "port": BASE_LISTENER_PORT + idx, "proxy": f"node_{idx}"})

    temp_cfg = {
        "allow-lan": False, "log-level": "silent",
        "dns": {"enable": True, "nameserver": ["8.8.8.8", "1.1.1.1"]},
        "proxies": temp_proxies, "listeners": listeners,
    }
    with open("temp_mihomo.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(temp_cfg, f, allow_unicode=True)

    mihomo_bin = _resolve_mihomo_bin()
    proc = subprocess.Popen([mihomo_bin, "-f", "temp_mihomo.yaml"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    await asyncio.sleep(2.5)

    print(f"[*] 已启动 Mihomo 隧道引擎，对 {len(candidates)} 个节点做真实出站穿透探测...")
    sem = asyncio.Semaphore(CONCURRENCY_TUNNEL)
    results = await asyncio.gather(*[
        probe_node_via_tunnel(candidates[i], BASE_LISTENER_PORT + i, sem)
        for i in range(len(candidates))])
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

    verified = [n for n in results if n and n.get("_exit_ip")]
    print(f"[*] 隧道真连接完成：{len(verified)} 个节点成功穿透并返回真实 exit_ip。")
    if not verified:
        return {}

    # 核验 exit_ip 纯净度
    exit_ips = [n["_exit_ip"] for n in verified]
    async with aiohttp.ClientSession() as session:
        purity = await ipapi_batch(session, exit_ips, GEOIP_FIELDS)

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    rejected_dirty = 0
    for node in verified:
        info = purity.get(node["_exit_ip"])
        if not info:
            continue
        cc = info.get("countryCode")
        city = info.get("city", "")
        is_proxy = info.get("proxy", False)
        is_hosting = info.get("hosting", False)
        as_info = (info.get("as", "") + " " + info.get("isp", "")).lower()

        if cc not in TARGET_REGIONS:
            continue
        # 硬淘汰：仅重灾/蜜罐机房 ASN；proxy 标志默认不淘汰（出口本就是代理）
        if any(bad in as_info for bad in BAD_ASN_KEYWORDS):
            rejected_dirty += 1
            continue
        if DROP_ON_PROXY_FLAG and is_proxy:
            rejected_dirty += 1
            continue

        region_cfg = TARGET_REGIONS[cc]
        group_title = None
        for en_city, zh in region_cfg["cities"].items():
            if city and en_city.lower() in city.lower():
                group_title = zh
                break
        if not group_title:
            if region_cfg.get("keep_other_cities", False):
                group_title = f"{region_cfg['name']}-其他"
            else:
                continue

        node["_purity_tag"] = "原生ISP" if not is_hosting else "纯净机房"
        penalty = (0 if not is_hosting else HOSTING_PENALTY) + (0 if not is_proxy else PROXY_PENALTY)
        node["_sort_score"] = node["_rtt_ms"] + penalty
        grouped.setdefault(group_title, []).append(node)

    print(f"[*] 纯净度过滤完成：剔除 {rejected_dirty} 个公开代理/脏机房 IP。")
    return grouped


# ================= 7. 生成 Mihomo 稳定配置 =================
def build_mihomo_config(grouped: Dict[str, List[Dict[str, Any]]], output_file: str = OUTPUT_FILE) -> None:
    final_proxies, city_groups = [], []
    for group_title, nodes in sorted(grouped.items()):
        nodes.sort(key=lambda x: x["_sort_score"])
        proxy_names = []
        for idx, node in enumerate(nodes, 1):
            clean = {k: v for k, v in node.items() if not k.startswith("_")}
            name = f"{group_title}-{idx:02d} [{node['_purity_tag']}|{node['_rtt_ms']}ms]"
            clean["name"] = name
            final_proxies.append(clean)
            proxy_names.append(name)
        city_groups.append({
            "name": f"🔒 {group_title} (固定纯净IP)", "type": "fallback",
            "proxies": proxy_names, "url": "https://www.gstatic.com/generate_204",
            "interval": 180, "lazy": False,
        })
        # 额外「防抖优选」url-test 组：长间隔 + 大 tolerance，只有明显更快才切，体验更稳
        if ENABLE_URLTEST_GROUPS:
            city_groups.append({
                "name": f"⚡ {group_title} (防抖优选)", "type": "url-test",
                "proxies": proxy_names, "url": URLTEST_URL,
                "interval": URLTEST_INTERVAL, "tolerance": URLTEST_TOLERANCE,
                "lazy": False,
            })

    config = {
        "mixed-port": 7890, "allow-lan": False, "mode": "rule",
        "log-level": "info", "ipv6": False,
        "dns": {"enable": True, "enhanced-mode": "fake-ip", "fake-ip-range": "198.18.0.1/16",
                "nameserver": ["https://dns.alidns.com/dns-query", "https://doh.pub/dns-query"],
                "fallback": ["https://1.1.1.1/dns-query", "https://dns.google/dns-query"]},
        "proxies": final_proxies,
        "proxy-groups": [
            {"name": "🚀 节点选择 (锁定纯净地区)", "type": "select",
             "proxies": [g["name"] for g in city_groups] + ["DIRECT"]},
            *city_groups,
        ],
        "rules": ["GEOIP,LAN,DIRECT,no-resolve", "GEOIP,CN,DIRECT,no-resolve",
                  "MATCH,🚀 节点选择 (锁定纯净地区)"],
    }
    with open(output_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
    print(f"[+] 最终配置已生成：{output_file}（收录 {len(final_proxies)} 个真落地纯净节点）")


# ================= 8. Mihomo 节点 -> sing-box outbound 转换 =================
def mihomo_to_singbox(node: Dict[str, Any], tag: str) -> Dict[str, Any]:
    """把内部 Mihomo(Clash Meta) 字典转成 sing-box outbound 对象。"""
    n = {k: v for k, v in node.items() if not k.startswith("_")}
    t = n.get("type")
    ob: Dict[str, Any] = {"tag": tag, "server": n.get("server"),
                          "server_port": int(n.get("port", 0))}

    if t == "vmess":
        ob["type"] = "vmess"
        ob["uuid"] = n.get("uuid")
        ob["security"] = n.get("cipher", "auto")
        ob["alter_id"] = int(n.get("alterId", 0))
        tls = {"enabled": bool(n.get("tls"))}
        if n.get("servername"): tls["server_name"] = n["servername"]
        if tls["enabled"]: ob["tls"] = tls
        if n.get("network") == "ws":
            ws = n.get("ws-opts", {}) or {}
            ob["transport"] = {"type": "ws", "path": ws.get("path", "/")}
            if ws.get("headers"): ob["transport"]["headers"] = ws["headers"]

    elif t == "vless":
        ob["type"] = "vless"
        ob["uuid"] = n.get("uuid")
        if n.get("flow"): ob["flow"] = n["flow"]
        if n.get("tls"):
            tls = {"enabled": True}
            if n.get("servername"): tls["server_name"] = n["servername"]
            if n.get("client-fingerprint"):
                tls["utls"] = {"enabled": True, "fingerprint": n["client-fingerprint"]}
            if n.get("reality-opts"):
                ro = n["reality-opts"]
                tls["reality"] = {"enabled": True,
                                  "public_key": ro.get("public-key", ""),
                                  "short_id": ro.get("short-id", "")}
            ob["tls"] = tls
        if n.get("network") in ("ws", "grpc"):
            transport = {"type": n["network"]}
            if n["network"] == "ws":
                ws = n.get("ws-opts", {}) or {}
                transport["path"] = ws.get("path", "/")
                if ws.get("headers"): transport["headers"] = ws["headers"]
            ob["transport"] = transport

    elif t == "trojan":
        ob["type"] = "trojan"
        ob["password"] = n.get("password")
        tls = {"enabled": True}
        if n.get("servername"): tls["server_name"] = n["servername"]
        if n.get("skip-cert-verify"): tls["insecure"] = True
        ob["tls"] = tls

    elif t == "ss":
        ob["type"] = "shadowsocks"
        ob["method"] = n.get("cipher")
        ob["password"] = n.get("password")

    elif t == "hysteria2":
        ob["type"] = "hysteria2"
        ob["password"] = n.get("password")
        tls = {"enabled": True}
        if n.get("sni"): tls["server_name"] = n["sni"]
        if n.get("skip-cert-verify"): tls["insecure"] = True
        ob["tls"] = tls

    else:
        # 未知类型：兜底保留通用字段，sing-box 会忽略或报错，但不至于丢信息
        ob["type"] = t or "direct"

    ob["tag"] = tag
    return {k: v for k, v in ob.items() if v not in (None, "")}


def build_singbox_config(grouped: Dict[str, List[Dict[str, Any]]],
                         output_file: str = SINGBOX_OUTPUT_FILE) -> None:
    """生成 sing-box JSON：每城一个 selector(手动锁IP) + 一个 urltest(防抖优选)。"""
    proxy_outbounds: List[Dict[str, Any]] = []
    group_tags: List[str] = []

    for group_title, nodes in sorted(grouped.items()):
        nodes.sort(key=lambda x: x["_sort_score"])
        city_tags = []
        for idx, node in enumerate(nodes, 1):
            tag = f"{group_title}-{idx:02d} [{node['_purity_tag']}|{node['_rtt_ms']}ms]"
            city_tags.append(tag)
            proxy_outbounds.append(mihomo_to_singbox(node, tag))

        # 固定：selector，用户点定 node_01 就不自动切（等价 fallback 的"锁死"意图）
        sel_tag = f"🔒 {group_title} (固定纯净IP)"
        outbounds_obj: Dict[str, Any] = {
            "type": "selector", "tag": sel_tag,
            "outbounds": city_tags + ["direct"],
            "default": city_tags[0] if city_tags else "direct",
        }
        # sing-box 的 selector 也支持 interrupt 逻辑靠 urltest；这里 selector 仅手动固定
        proxy_outbounds.append(outbounds_obj)
        group_tags.append(sel_tag)

        if ENABLE_URLTEST_GROUPS and city_tags:
            ut_tag = f"⚡ {group_title} (防抖优选)"
            proxy_outbounds.append({
                "type": "urltest", "tag": ut_tag, "outbounds": city_tags,
                "url": URLTEST_URL, "interval": f"{URLTEST_INTERVAL}s",
                "idle_timeout": "30m", "interrupt_connect_latency": "3s",
            })
            group_tags.append(ut_tag)

    main_tag = "🚀 节点选择 (锁定纯净地区)"
    config = {
        "log": {"level": "info"},
        "dns": {
            "servers": [
                {"tag": "local", "address": "https://dns.alidns.com/dns-query",
                 "strategy": "prefer_ipv4"},
                {"tag": "remote", "address": "https://1.1.1.1/dns-query",
                 "strategy": "prefer_ipv4"},
            ],
            "rules": [{"action": "route", "geosite": "cn", "server": "local"},
                      {"action": "route", "server": "remote"}],
        },
        "inbounds": [{"type": "mixed", "tag": "in", "listen": "127.0.0.1", "port": 7890,
                      "sniff": True, "sniff_override_destination": True}],
        "outbounds": [
            {"type": "selector", "tag": main_tag, "outbounds": group_tags + ["direct"]},
            *proxy_outbounds,
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
            {"type": "dns", "tag": "dns-out"},
        ],
        "route": {
            "rules": [
                {"protocol": "dns", "action": "hijack-dns"},
                {"rule_set": "geoip-cn", "outbound": "direct"},
                {"domain_suffix": ".cn", "outbound": "direct"},
            ],
            "final": main_tag,
            "auto_detect_interface": True,
        },
        "route_rule_set": [],
        "experimental": {"cache_file": {"enabled": True}},
    }
    # 移除会触发 sing-box 校验失败的占位 rule_set（geodata 未随包，用户自备时再补）
    config["route"]["rules"] = [r for r in config["route"]["rules"] if "rule_set" not in r]

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"[+] sing-box 配置已生成：{output_file}")


async def main() -> None:
    raw = await fetch_subscriptions(SUB_URLS)
    if not raw:
        print("[-] 未获取到任何节点，请检查 config.SUB_URLS。")
        return
    sem = asyncio.Semaphore(CONCURRENCY_PING)
    checked = await asyncio.gather(*[tcp_ping(n, sem) for n in raw])
    alive = [n for n in checked if n]
    print(f"[*] TCP 初筛存活：{len(alive)} 个。")
    if not alive:
        return
    await pre_tag_region(alive)
    grouped = await verify_exit_and_purity(alive)
    if not grouped:
        print("[-] 没有节点通过真连接与纯净度核验。")
        return
    build_mihomo_config(grouped)
    build_singbox_config(grouped)


if __name__ == "__main__":
    if os.environ.get("DRY_RUN") == "1":
        from selftest import run_selftest
        run_selftest()
    else:
        asyncio.run(main())
