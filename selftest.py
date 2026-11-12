# -*- coding: utf-8 -*-
"""离线自检：不联网，验证解析 / 亚洲保底名额 / 配置生成三段核心逻辑。
运行：DRY_RUN=1 python aggregator.py   或   python selftest.py
"""
import asyncio, os, sys, yaml

from config import TARGET_REGIONS, ASIAN_COUNTRY_CODES, MAX_VERIFY_NODES, ASIA_MIN_RATIO, ENABLE_URLTEST_GROUPS
from aggregator import (parse_uri, classify_region, select_candidates_with_asia_quota,
                        build_mihomo_config, build_singbox_config, mihomo_to_singbox)


def _node(server, port, tcp_ms, hint, exit_ip=None, rtt=None, purity="原生ISP", score=None):
    n = {"name": f"{server}", "type": "vmess", "server": server, "port": port,
         "uuid": "00000000-0000-0000-0000-000000000000", "alterId": 0, "cipher": "auto", "udp": True}
    if tcp_ms is not None: n["_tcp_ms"] = tcp_ms
    if hint: n["_hint_region"] = hint
    if exit_ip: n["_exit_ip"] = exit_ip
    if rtt is not None: n["_rtt_ms"] = rtt
    if purity: n["_purity_tag"] = purity
    n["_sort_score"] = score if score is not None else (rtt or 0)
    return n


def test_parse_uri():
    # vless 明文链接
    vless = ("vless://11111111-2222-3333-4444-555555555555"
             "@tokyo.example.com:443?security=tls&sni=tokyo.example.com&type=ws"
             "#%F0%9F%87%AF%F0%9F%87%B5%E6%97%A5%E6%9C%AC")
    n = parse_uri(vless)
    assert n["type"] == "vless" and n["server"] == "tokyo.example.com" and n["port"] == 443, n
    assert n["tls"] is True and n["servername"] == "tokyo.example.com", n
    assert n["name"] == "🇯🇵日本", n
    assert n["network"] == "ws", n
    print("  [ok] parse_uri(vless)")


def test_classify_region():
    assert classify_region("JP", "Tokyo") == "asia"
    assert classify_region("HK", "") == "asia"
    assert classify_region("US", "Seattle") == "america"
    assert classify_region("DE", "Frankfurt") == "europe"
    assert classify_region("BR", "Sao Paulo") == "other"
    print("  [ok] classify_region")


def test_asia_quota():
    """关键测试：美国 runner 下美国 TCP 延迟碾压亚洲，亚洲仍应拿到保底名额。"""
    alive = []
    # 1500 个美国节点，延迟都很低（模拟美国 runner 偏袒；池须大于 MAX_VERIFY_NODES 才能测出名额上限与饿死效应）
    for i in range(1500):
        alive.append(_node(f"us{i}.example.com", 443, 8 + (i % 40), "america"))
    # 80 个亚洲节点，延迟偏高（被全局排序挤到后面）
    for i in range(80):
        alive.append(_node(f"jp{i}.example.com", 443, 120 + (i % 60), "asia"))

    chosen = select_candidates_with_asia_quota(alive, MAX_VERIFY_NODES, ASIA_MIN_RATIO)
    asia_chosen = sum(1 for n in chosen if n["_hint_region"] == "asia")
    assert len(chosen) == MAX_VERIFY_NODES, len(chosen)
    # 亚洲池 80 个 < 250*0.55≈137，应全部入选（80），证明没被美国节点饿死
    assert asia_chosen == 80, asia_chosen

    # 反例：去掉保底、纯全局延迟排序，亚洲会被美国节点挤出名额
    naive = sorted(alive, key=lambda x: x["_tcp_ms"])[:MAX_VERIFY_NODES]
    naive_asia = sum(1 for n in naive if n["_hint_region"] == "asia")
    assert naive_asia < asia_chosen, (naive_asia, asia_chosen)
    print(f"  [ok] 亚洲保底：{asia_chosen} 个亚洲节点入选 vs 纯排序仅 {naive_asia} 个")


def test_asia_quota_small_pool():
    """亚洲候选不足保底额时，空余名额应回填给 others，总数仍等于 quota。"""
    alive = [_node(f"jp{i}.com", 443, 150 + i, "asia") for i in range(10)]
    alive += [_node(f"us{i}.com", 443, 10 + i, "america") for i in range(300)]
    chosen = select_candidates_with_asia_quota(alive, MAX_VERIFY_NODES, ASIA_MIN_RATIO)
    assert len(chosen) == min(MAX_VERIFY_NODES, len(alive)), len(chosen)
    assert sum(1 for n in chosen if n["_hint_region"] == "asia") == 10
    print("  [ok] 亚洲池不足时名额回填，总数守恒")


def test_build_config():
    grouped = {
        "🇯🇵 日本-东京": [_node("jp-a", 443, None, "asia", "1.1.1.1", 30),
                        _node("jp-b", 443, None, "asia", "1.1.1.2", 50)],
        "🇺🇸 美国-洛杉矶": [_node("us-a", 443, None, "america", "2.2.2.2", 90)],
    }
    out = "_selftest_out.yaml"
    build_mihomo_config(grouped, out)
    cfg = yaml.safe_load(open(out, encoding="utf-8"))
    assert "proxies" in cfg and len(cfg["proxies"]) == 3, cfg
    groups = cfg["proxy-groups"]
    assert groups[0]["type"] == "select", groups[0]
    fb = [g for g in groups if g["type"] == "fallback"]
    assert len(fb) == 2, fb
    # 城市组内按 _sort_score 升序：东京组第一个应是 rtt=30 的 jp-a
    assert "30ms" in fb[0]["proxies"][0], fb[0]["proxies"]
    # 防抖优选 url-test 组（每城一个，tolerance 500）
    if ENABLE_URLTEST_GROUPS:
        ut = [g for g in groups if g["type"] == "url-test"]
        assert len(ut) == 2, ut
        assert all(g.get("tolerance") == 500 for g in ut), ut
    os.remove(out)
    print("  [ok] build_mihomo_config 生成 select + fallback" + (" + url-test 组" if ENABLE_URLTEST_GROUPS else ""))


def test_singbox_config():
    grouped = {
        "🇯🇵 日本-东京": [_node("jp-a", 443, None, "asia", "1.1.1.1", 30),
                        _node("jp-b", 443, None, "asia", "1.1.1.2", 50)],
        "🇺🇸 美国-洛杉矶": [_node("us-a", 443, None, "america", "2.2.2.2", 90)],
    }
    out = "_selftest_sb.json"
    build_singbox_config(grouped, out)
    import json
    cfg = json.load(open(out, encoding="utf-8"))
    ob_types = {o.get("type") for o in cfg["outbounds"]}
    assert "selector" in ob_types and "urltest" in ob_types and "mixed" not in ob_types
    assert cfg["inbounds"][0]["type"] == "mixed", cfg["inbounds"]
    # 3 个节点 + 城市组 + 主选择器 + direct/block/dns-out
    tags = [o.get("tag") for o in cfg["outbounds"]]
    assert "🚀 节点选择 (锁定纯净地区)" in tags, tags
    vless_node = mihomo_to_singbox({"type": "vless", "server": "s", "port": 443,
                                    "uuid": "u", "tls": True, "servername": "sni",
                                    "network": "ws", "ws-opts": {"path": "/x", "headers": {"Host": "h"}}}, "t")
    assert vless_node["transport"] == {"type": "ws", "path": "/x", "headers": {"Host": "h"}}, vless_node
    assert vless_node["tls"]["server_name"] == "sni", vless_node
    os.remove(out)
    print("  [ok] build_singbox_config / mihomo_to_singbox 转换正确")


def run_selftest():
    print("[selftest] 离线自检开始（不联网）...")
    test_parse_uri()
    test_classify_region()
    test_asia_quota()
    test_asia_quota_small_pool()
    test_build_config()
    test_singbox_config()
    print("[selftest] 全部通过 ✅")
    return True


if __name__ == "__main__":
    ok = run_selftest()
    sys.exit(0 if ok else 1)
