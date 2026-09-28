#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPTV 直播源自动采集 / 合并 / 去重 / 校验 / 清晰度筛选
==================================================
- 从 sources.txt 读取公开 M3U 源
- 合并、按 (频道名,URL) 去重
- 可选存活校验（HEAD 探测，失败回退 GET 首字节；超时/异常则保留，避免误删）
- 按清晰度筛选输出：index.m3u(全量) / hd.m3u(1080P+) / 4k.m3u(4K·UHD) / index.txt(DIYP/OK影视直播格式)

仅聚合「公开可用」的链接，不托管任何流媒体内容。仅供个人测试/研究使用。
环境变量：
  VALIDATE=1 开启存活校验（默认开）；VALIDATE=0 关闭
  ONLY_HD=1  仅输出 1080P+（默认关）
"""

import os
import re
import sys
import time
import concurrent.futures as cf
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(ROOT, "sources.txt")
OUT_DIR = os.path.join(ROOT, "output")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IPTVCollector/1.0)"}
EPG = "https://live.fanmingming.com/e.xml"  # 通用节目单（支持 EPG 的播放器可用）

# 清晰度关键词（用于筛选 1080P / 4K）
HD_KEYWORDS = re.compile(r"(1080|全高清|超清|高清|hd|fhd|蓝光|bluray)", re.I)
UHD_KEYWORDS = re.compile(r"(4k|2160|uhd|ultra)", re.I)


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
    """拉取源并读取前 2MB（足够解析 M3U），避免大文件拖垮 Runner。"""
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
            r.raise_for_status()
            chunks, total = [], 0
            for chunk in r.iter_content(8192):
                chunks.append(chunk)
                total += len(chunk)
                if total > 100_000_000:  # 安全上限 100MB，避免截断 iptv-org 等大列表
                    break
            return b"".join(chunks).decode("utf-8", "ignore")
        except Exception as e:
            if attempt == retries:
                print(f"[WARN] 拉取失败 {url}: {e}")
                return None
    return None


def check_alive(url, timeout=6):
    """轻量存活探测：HEAD 优先，失败回退 GET 首字节。异常/超时返回 True（不确定则保留）。"""
    try:
        try:
            r = requests.head(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            if r.status_code < 400:
                return True
        except Exception:
            pass
        r = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        try:
            next(r.iter_content(1024))
            return True
        finally:
            r.close()
    except Exception:
        return False


def is_uhd(name, attrs):
    s = f"{name} {attrs.get('group-title', '')}"
    return bool(UHD_KEYWORDS.search(s))


def is_hd(name, attrs):
    s = f"{name} {attrs.get('group-title', '')}"
    return bool(HD_KEYWORDS.search(s)) or is_uhd(name, attrs)


def write_m3u(path, items):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'#EXTM3U x-tvg-url="{EPG}"\n')
        for (name, url), attrs in items:
            logo = attrs.get("tvg-logo", "")
            grp = attrs.get("group-title", "")
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
        items = [it for it in items if alive.get(it[0][1], True)]
        print(f"[INFO] 校验后存活频道数: {len(items)}")

    if only_hd:
        items = [it for it in items if is_hd(*it[0])]

    # 4) 清晰度筛选
    hd_items = [it for it in items if is_hd(*it[0])]
    uhd_items = [it for it in items if is_uhd(*it[0])]

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
