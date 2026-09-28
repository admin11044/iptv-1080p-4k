# IPTV 直播源自动采集器（GitHub 全自动版）

在 GitHub 上托管、用 GitHub Actions **定时自动**采集/合并/校验公开直播源，
去重 + 按清晰度筛选，输出 M3U / TXT，直接在 **OK影视** 里订阅，全程无需手动维护。

## 它做什么
1. 从 `sources.txt` 读取一批公开 M3U 源（fanmingming / iptv-org / Free-TV 等）。
2. 合并、按「频道名+URL」去重。
3. 并发存活校验（HEAD 探测，失败回退 GET 首字节），自动剔除死链。
4. 按清晰度筛选，生成 4 个产物：
   - `output/index.m3u` —— 全量存活频道
   - `output/hd.m3u`   —— 1080P / 全高清 / 蓝光（含 4K）
   - `output/4k.m3u`   —— 仅 4K / 2160P / UHD
   - `output/index.txt`—— DIYP/OK影视 直播 TXT 格式（#genre# 分组）
5. 每 6 小时（北京时间 02/08/14/20 点）自动跑一次并回写仓库。

## 一次性部署（约 5 分钟，之后全自动）
1. 在 GitHub 新建一个**公开**仓库（如 `my-iptv`）。
2. 把本目录全部文件（`collect.py` / `sources.txt` / `requirements.txt` / `.github/`）推上去。
3. 仓库 **Settings → Actions → General** 确认 Workflow 权限为 `Read and write`（默认即可）。
4. 完毕。Actions 会按 cron 自动运行；也可在 Actions 页点 `Run workflow` 立即跑一次验证。

> 想改源？编辑 `sources.txt` 增删地址，推送即触发更新。
> 想关闭校验（更快、更省 Actions 时长）：在 `update.yml` 里把 `VALIDATE: "1"` 改成 `"0"`。

## 在 OK影视 里订阅（重点）
OK影视「直播」支持 **M3U** 与 **TXT** 两种订阅格式。
因 `raw.githubusercontent.com` 在国内常被墙/限速，**务必用镜像前缀**访问：

把你仓库的订阅地址前面拼一个镜像域名即可，例如你的 `4k.m3u` 原始地址是：
```
https://raw.githubusercontent.com/<你的用户名>/<仓库名>/main/output/4k.m3u
```
任选一种镜像前缀（挑一个能打开的）：
```
https://ghproxy.net/https://raw.githubusercontent.com/<用户名>/<仓库名>/main/output/4k.m3u
https://ghfast.top/https://raw.githubusercontent.com/<用户名>/<仓库名>/main/output/4k.m3u
https://gh.llkk.cc/https://raw.githubusercontent.com/<用户名>/<仓库名>/main/output/4k.m3u
https://gh.llkk.cc/https://raw.githubusercontent.com/<用户名>/<仓库名>/main/output/hd.m3u
```

OK影视 添加步骤：
1. 打开 OK影视 → 右下角「设置」→「直播」。
2. 把上面的镜像 URL 粘贴进订阅框，确定。
3. 返回首页「直播」页即可看到频道；卡顿可在设置里点「刷新」重新拉取最新列表。

> 想要 1080P 为主就订阅 `hd.m3u`；只想要 4K/UHD 就订阅 `4k.m3u`；全量选 `index.m3u`。
> 部分 TVBox 内核的 OK影视 版本也接受 `index.txt`（DIYP 格式）。

## 本仓库现成订阅链接（直接复制粘贴）

仓库已设为**公开**，下面是即拷即用的镜像链接（国内优先用 ghproxy.net；若打不开换 ghfast.top / gh.llkk.cc）：

- **4K / UHD（6 路真 4K 源）**
  `https://ghproxy.net/https://raw.githubusercontent.com/admin11044/iptv-1080p-4k/main/output/4k.m3u`
- **1080P+（33 路高码率 1080P 源）**
  `https://ghproxy.net/https://raw.githubusercontent.com/admin11044/iptv-1080p-4k/main/output/hd.m3u`
- **全量（已剔除低质，约 1700 路）**
  `https://ghproxy.net/https://raw.githubusercontent.com/admin11044/iptv-1080p-4k/main/output/index.m3u`
- **OK影视 TXT 格式（DIYP / #genre# 分组）**
  `https://ghproxy.net/https://raw.githubusercontent.com/admin11044/iptv-1080p-4k/main/output/index.txt`

裸链备用（国内可能慢/被墙）：
`https://raw.githubusercontent.com/admin11044/iptv-1080p-4k/main/output/4k.m3u`

## 关于「1080P / 4K」的实话
- **低质频道已强制剔除**：脚本在筛选时直接丢弃名称/分组里含
  `240/360/480/576/720/标清/流畅/普清/低清/CAM/省流` 等低码率、模糊标签的频道，
  只保留明确标注 `1080P/全高清/超清/蓝光` 及 `4K/2160/UHD` 的**高码率**源（见 `collect.py` 的 `LOW_QUALITY`）。
- 免费公开直播源里**真正稳定 4K 的极少**，多为 1080P，且会随源变动。
  fanmingming 等源带有 CCTV 4K 测试频道，会被 `4k.m3u` 收录。
- 清晰度筛选是按**频道名/分组里的关键词**（如 “4K”“1080P”“超清”）匹配的，
  并不能 100% 保证物理分辨率——脚本不做逐流码率探测（太重、易误杀）。
- 存活校验只验证「链接可达」，不验证画质与流畅度；播放卡顿多半是源本身或网络问题。

## 可选：开启 GitHub Pages（多一条更稳的访问线路）
仓库 **Settings → Pages → Source** 选 `GitHub Actions`，
再把 `update.yml` 末尾追加上传/部署 Pages 的步骤即可（见仓库 Wiki / 注释）。
Pages 地址形如 `https://<用户名>.github.io/<仓库名>/output/4k.m3u`，同样建议走镜像。

## 免责声明
本项目仅聚合互联网上**公开可用**的直播链接，不托管、不分发任何流媒体内容。
所有链接版权归原提供者所有，请遵守所在地法律法规，仅用于个人测试/研究。
