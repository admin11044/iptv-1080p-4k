#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPTV 直播源自动采集 / 合并 / 去重 / 校验 / 清晰度筛选 / 分组规范
==============================================================
仅聚合「公开可用」的链接，不托管任何流媒体内容。仅供个人测试/研究使用。

设计目标（针对中国用户 / OK影视，避免卡顿 & 分组混乱）：
- 源只收录「国内可直连」的直播源（见 sources.txt），从源头杜绝海外源导致卡顿；
- HD/4K 列表强制仅保留「中国频道」，剔除海外伪高清（如 Rai 4K、Ando TV、10 HD）；
- 剔除低码率/模糊/标清/720P 等低质频道（用户要求只保留高码率 1080P/4K）；
- 剔除 [Geo-blocked]/[Not 24/7] 等不可用标记频道；
- 重新规范分组：央视频道 / 卫视频道 / 地方频道 / 4K超清 / 体育 / 港澳台 / 少儿 / 影视 / 纪实 / 新闻 / 其他。
"""

import os
import re
import time
import concurrent.futures as cf
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(ROOT, "sources.txt")
OUT_DIR = os.path.join(ROOT, "output")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IPTVCollector/1.0)"}
EPG = "https://live.fanmingming.com/e.xml"  # 通用节目单（支持 EPG 的播放器可用）

# 清晰度关键词（用于筛选 1080P / 4K）；央视/卫视在大陆均为高清播出，一并纳入
HD_KEYWORDS = re.compile(r"(1080|全高清|超清|高清|hd\b|fhd|蓝光|bluray|blu-ray)", re.I)
UHD_KEYWORDS = re.compile(r"(4k|2160|uhd|ultra|超高清)", re.I)
# 低质/低码率/模糊标签：命中即剔除（用户要求只要高码率 1080P/4K）
LOW_QUALITY = re.compile(
    r"(240|360|480|576|720|sd\b|标清|流畅|普清|低清|ld\b|came|camrip|省流|极速|流畅版|马赛克|卡顿|测试源|test源)",
    re.I,
)
# 不可用标记：命中即剔除
BAD_MARKERS = re.compile(
    r"(\[geo-blocked\]|\[not 24/7\]|\[geo blocked\]|\[test\]|\[demo\]|\[停播\]|\[失效\])",
    re.I,
)
# 中国频道判定：频道名含中日韩汉字即视为中文频道（海外伪高清多为纯英文，会被排除）
CJK = re.compile(r"[\u3400-\u9fff]")


def is_chinese(name):
    """频道名含汉字 → 视为中国频道。HD/4K 列表据此剔除海外伪高清。"""
    return bool(CJK.search(name))


def parse_m3u(text):
    """解析 M3U：返回 [(name, url, attrs_dict), ...]"""
    channels = []
    pending = None  # (name, attrs)
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            attrs = dict(re.findall(r'(\w[\w-]*?)="([^"]*)"', line))
            name = line.rsplit(",", 1)[-1].strip()
            pending = (name, attrs)
        elif line.startswith("#"):
            if pending is not None and line.startswith("#EXTGRP:"):
                pending[1].setdefault("group-title", line.split(":", 1)[-1].strip())
            continue
        else:
            url = line
            if pending and url.startswith("http"):
                name, attrs = pending
                channels.append((name, url, attrs))
            pending = None
    return channels


def fetch_source(url, timeout=25, retries=2):
    """拉取源并读取（上限 100MB，避免大列表拖垮 Runner）。"""
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
            r.raise_for_status()
            chunks, total = [], 0
            for chunk in r.iter_content(8192):
                chunks.append(chunk)
                total += len(chunk)
                if total > 100_000_000:
                    break
            return b"".join(chunks).decode("utf-8", "ignore")
        except Exception as e:
            if attempt == retries:
                print(f"[WARN] 拉取失败 {url}: {e}")
                return None
    return None


def check_alive(url, timeout=6):
    """轻量存活探测：HEAD 优先，失败回退 GET 首字节。
    返回 False 仅当「明确失效」（HTTP 404/410）；其余一律保留——
    因为 GitHub 运行节点在美国，测中国 CDN（如广东联通）多半超时/403，
    属「中国能播、海外测不了」的误判区间，不能据此删链，否则列表会被清空。
    """
    try:
        try:
            r = requests.head(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            if r.status_code in (404, 410):
                return False  # 明确失效，剔除
            if r.status_code < 400:
                return True
        except Exception:
            pass
        r = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        try:
            if r.status_code in (404, 410):
                return False
            next(r.iter_content(1024))
            return True
        finally:
            r.close()
    except Exception:
        return True  # 不确定（超时/连接拒绝等）→ 保留，交由用户端实测
    return True


def is_uhd(name, attrs):
    s = f"{name} {attrs.get('group-title', '')} {attrs.get('tvg-name', '')}"
    return bool(UHD_KEYWORDS.search(s))


def is_hd(name, attrs):
    s = f"{name} {attrs.get('group-title', '')} {attrs.get('tvg-name', '')}"
    if is_uhd(name, attrs):
        return True
    if HD_KEYWORDS.search(s):
        return True
    # 央视 / 卫视在大陆均为高清播出
    if re.search(r"(CCTV|CGTN|央视|中央)", s):
        return True
    if re.search(r"卫视", name):
        return True
    return False


def is_low_quality(name, attrs):
    """低码率/模糊/标清/720P 等明确低质标签 → 剔除"""
    s = f"{name} {attrs.get('group-title', '')}"
    return bool(LOW_QUALITY.search(s))


def has_bad_marker(name, attrs):
    s = f"{name} {attrs.get('group-title', '')}"
    return bool(BAD_MARKERS.search(s))


def normalize_group(name, g):
    """把杂乱分组规范为干净的顶层分组（适配 OK影视 / TVBox 菜单）。"""
    s = f"{name} {g}"
    if re.search(r"CCTV|CGTN|央视|中央", s):
        return "央视频道"
    if re.search(r"4K|2160|UHD|超高清", s):
        return "4K超清"
    if re.search(r"卫视", name):
        return "卫视频道"
    if re.search(r"体育|运动|NBA|足球|篮球|赛事|奥运", s):
        return "体育频道"
    if re.search(r"港|澳|台|HK|Macau|Taiwan|Hong", s):
        return "港澳台"
    if re.search(r"少儿|动画|卡通|亲子", s):
        return "少儿频道"
    if re.search(r"电影|影视|剧场|综艺", s):
        return "影视频道"
    if re.search(r"纪录|探索|Discovery|科教|知识", s):
        return "纪实频道"
    if re.search(r"新闻|财经|法治|军事", s):
        return "新闻频道"
    if re.search(r"频道", g) and not re.search(r"高清|备用|Undefined|General|Undefined", g):
        return "地方频道"
    if re.search(r"高清|卫视|央视|备用", g, re.I):
        return g  # 保留 fanmingming 原生高清分组（如 卫视高清 / 央视高清）
    return "其他"


def write_m3u(path, items):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'#EXTM3U x-tvg-url="{EPG}"\n')
        for (name, url), attrs in items:
            logo = attrs.get("tvg-logo", "")
            grp = attrs.get("group-title", "其他")
            tname = attrs.get("tvg-name", name)
            f.write(f'#EXTINF:-1 tvg-name="{tname}" tvg-logo="{logo}" group-title="{grp}",{name}\n')
            f.write(url + "\n")


def write_txt(path, items):
    """DIYP / OK影视直播 TXT 格式：#genre# 分组 + 名称,url"""
    groups = {}
    for (name, url), attrs in items:
        grp = attrs.get("group-title", "其他") or "其他"
        groups.setdefault(grp, []).append((name, url))
    with open(path, "w", encoding="utf-8") as f:
        for grp, chs in groups.items():
            f.write(f"{grp},#genre#\n")
            for name, url in chs:
                f.write(f"{name},{url}\n")
            f.write("\n")


def main():
    validate = os.environ.get("VALIDATE", "1") == "1"
    only_hd = os.environ.get("ONLY_HD", "0") == "1"

    # 1) 读取源列表
    sources = []
    with open(SOURCES_FILE, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            sources.append(ln)
    print(f"[INFO] 源数量: {len(sources)}")

    # 2) 拉取 + 解析 + 去重
    seen = {}
    for url in sources:
        text = fetch_source(url)
        if not text:
            continue
        for name, u, attrs in parse_m3u(text):
            key = (name, u)
            if key not in seen:
                seen[key] = attrs
    print(f"[INFO] 去重后频道数: {len(seen)}")

    items = list(seen.items())

    # 3) 存活校验（并发）
    if validate:
        urls = [u for (_, u), _ in items]
        alive = {}
        with cf.ThreadPoolExecutor(max_workers=32) as ex:
            fut = {ex.submit(check_alive, u): u for u in urls}
            for i, f in enumerate(cf.as_completed(fut), 1):
                alive[fut[f]] = f.result()
                if i % 300 == 0:
                    print(f"[INFO] 校验进度 {i}/{len(urls)}")
        items = [it for it in items if alive.get(it[0][1], False)]
        print(f"[INFO] 校验后存活频道数: {len(items)}")

    # 3.5) 剔除不可用标记 & 低码率/模糊/标清/720P 等低质频道
    before = len(items)
    items = [it for it in items if not has_bad_marker(it[0][0], it[1])]
    items = [it for it in items if not is_low_quality(it[0][0], it[1])]
    print(f"[INFO] 剔除标记/低质频道: {before - len(items)} | 剩余: {len(items)}")

    if only_hd:
        items = [it for it in items if is_hd(it[0][0], it[1]) and is_chinese(it[0][0])]

    # 4) 清晰度筛选（HD/4K 仅保留中国频道，剔除海外伪高清）
    hd_items = [it for it in items if is_hd(it[0][0], it[1]) and is_chinese(it[0][0])]
    uhd_items = [it for it in items if is_uhd(it[0][0], it[1]) and is_chinese(it[0][0])]

    # 5) 规范分组（在输出前统一改写 group-title）
    for (name, _), attrs in items:
        attrs["group-title"] = normalize_group(name, attrs.get("group-title", ""))

    os.makedirs(OUT_DIR, exist_ok=True)
    write_m3u(os.path.join(OUT_DIR, "index.m3u"), items)
    write_m3u(os.path.join(OUT_DIR, "hd.m3u"), hd_items)
    write_m3u(os.path.join(OUT_DIR, "4k.m3u"), uhd_items)
    write_txt(os.path.join(OUT_DIR, "index.txt"), items)

    with open(os.path.join(OUT_DIR, "stats.txt"), "w", encoding="utf-8") as f:
        f.write(f"更新时间(UTC): {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"全量频道: {len(items)}\n1080P+: {len(hd_items)}\n4K/UHD: {len(uhd_items)}\n")

    print(f"[DONE] 全量 {len(items)} | 1080P+ {len(hd_items)} | 4K/UHD {len(uhd_items)}")


if __name__ == "__main__":
    main()
