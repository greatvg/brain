#!/usr/bin/env python3
"""
search_web.py — 中英文通用搜索工具（固定位置版本，工作区更替也不丢）

位置：~/.workbuddy/tools/search_web.py（唯一归属，勿在工作区留副本）

实测通道（2026-09-15）：
  - DuckDuckGo 搜索（ddgs 库）：中英文均可用，免费无 key ✅
  - GitHub 仓库搜索：找开源方案 / 代码 ✅
  - Jina Reader：任意网页转 markdown ✅
  - Google 网页搜索：反爬拦截页，已废 ❌（勿重试）
  - Bing：跳中国版，英文质量差 ❌
  - agent-browser：本环境一切 spawn 类命令必 SIGTERM ❌

中文查询必读：
  ddgs 默认 region=us-en，中文查询会按英/日索引逻辑处理，出现语种误判
  （实测：查「国内」返回 Yahoo!ニュース / NHKニュース 等日文结果）与分词噪音。
  本脚本已内置语种自动检测：含中文 → region=cn-zh，其余 → us-en；可用 --region 覆盖。

代理端口（禁止写死具体值 — 每次会话可能不同）：
  三级回退：① 读 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY 等环境变量 → TCP 探测是否真通
           ② 探测本机候选端口（Clash/v2ray/会话代理常见端口）
           ③ 都不通 → 直连
  注意：ddgs 必须在 import ddgs 之前设好代理环境变量（primp 构造时读取），脚本已处理。

用法：
  python ~/.workbuddy/tools/search_web.py "查询词"                 # 通用搜索（语种自动识别）
  python ~/.workbuddy/tools/search_web.py "查询词" --n 10          # 指定条数
  python ~/.workbuddy/tools/search_web.py "查询词" --news          # 新闻搜索
  python ~/.workbuddy/tools/search_web.py "查询词" --github        # GitHub 仓库搜索（按 star）
  python ~/.workbuddy/tools/search_web.py "查询词" --region cn-zh  # 手动指定区域
  python ~/.workbuddy/tools/search_web.py URL --fetch              # 网页正文转 markdown
  python ~/.workbuddy/tools/search_web.py "查询词" --proxy-check   # 只看代理探测结果
"""

import argparse
import json
import os
import re
import socket
import sys
from pathlib import Path

# 自动切换到装有 ddgs 的解释器（避免用户用系统 python 跑时报 ImportError）
_VENV_PY = Path.home() / ".workbuddy" / "binaries" / "python" / "envs" / "default" / "Scripts" / "python.exe"


def _ensure_deps():
    try:
        import ddgs  # noqa: F401
        return True
    except ImportError:
        if _VENV_PY.exists() and Path(sys.executable) != _VENV_PY:
            # 用子进程委托（不用 os.execv：实测 execv 替换进程后输出会丢失，表现为静默无结果）
            import subprocess
            sys.stderr.write("[info] 当前解释器无 ddgs，改用 venv 解释器执行\n")
            r = subprocess.run([str(_VENV_PY), str(Path(__file__).resolve())] + sys.argv[1:])
            sys.exit(r.returncode)
        return False


_ensure_deps()

# 本机候选代理端口（探测用；不写死为"规则"，只是探测顺序）
CANDIDATE_PORTS = (7890, 7897, 10809, 10808, 1080, 8118, 8888, 20171, 33210, 7790)
_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def _tcp_alive(proxy_url, timeout=0.8):
    """TCP 级连通性探测（毫秒级，不发 HTTP 请求）"""
    m = re.match(r"(?:https?|socks5h?)://(?:[^@]*@)?([^:/]+):(\d+)", proxy_url)
    if not m:
        return False
    try:
        s = socket.create_connection((m.group(1), int(m.group(2))), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def _proxy_works(proxy_url, timeout=8):
    """真实请求级验证代理是否可用。

    为什么不能只做 TCP 探测（2026-09-16 实测）：本机会话代理会出现"端口能握手、
    HTTP 请求全超时"的**假活**状态。只探端口会把坏代理当好的用，导致所有通道
    集体超时，看起来像"搜索工具坏了"，实际是代理坏了 —— 误诊方向完全错。
    """
    import urllib.request
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
        with op.open("https://duckduckgo.com/", timeout=timeout) as r:
            return r.status < 500
    except Exception:
        return False


def resolve_proxy(verbose=False):
    """三级回退取代理：环境变量 → 候选端口探测 → 直连(None)"""
    cands = []
    for k in _ENV_KEYS:
        v = os.environ.get(k)
        if v and v not in cands:
            cands.append(v)
    for p in CANDIDATE_PORTS:
        u = f"http://127.0.0.1:{p}"
        if u not in cands:
            cands.append(u)

    for c in cands:
        if _tcp_alive(c):
            if verbose:
                sys.stderr.write(f"[proxy] 使用 {c}\n")
            return c
    if verbose:
        sys.stderr.write("[proxy] 无可用代理，直连\n")
    return None


PROXY = None if "--no-proxy" in sys.argv else resolve_proxy(verbose=("--proxy-check" in sys.argv))

# 代理假活防线：TCP 通 ≠ 能转发。探测到代理后再用真实请求验一次，假的直接丢掉。
if PROXY and not _proxy_works(PROXY):
    sys.stderr.write(f"[warn] 代理 {PROXY} TCP 通但请求超时（假活），已降级直连\n")
    PROXY = None

# ddgs/primp 会从环境变量读代理；无可用代理时必须清掉坏值，否则连接仍走死代理
_ENV_KEYS_ALL = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "DDGS_PROXY",
                 "http_proxy", "https_proxy", "all_proxy")
for _k in _ENV_KEYS_ALL:
    if PROXY:
        os.environ[_k] = PROXY
    else:
        os.environ.pop(_k, None)


def detect_region(query):
    """按查询语种自动选 region（防中文语种误判）"""
    return "cn-zh" if any("\u4e00" <= c <= "\u9fff" for c in query) else "us-en"


def search_text(query, max_results=10, region=None):
    """通用搜索：重试 3 次。

    实测（2026-09-16）：ddgs text 通道会偶发 TimeoutException——同一查询连续两次
    都超时，但通道本身没坏。**不重试就会把"能用的通道"误判成"通道坏了"**，进而
    触发不必要的降级。news 通道早已有重试，text 通道漏了，这是缺陷补上。
    """
    import time
    from ddgs import DDGS
    region = region or detect_region(query)
    last = None
    for attempt in range(3):
        try:
            with DDGS() as d:
                r = list(d.text(query, region=region, max_results=max_results))
            if r:
                return r
            last = last or RuntimeError("No results found")
        except Exception as e:
            last = e
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    if last:
        raise last
    return []


def search_news(query, max_results=10, region=None):
    """新闻搜索：重试 + 区域回落 + 通用搜索兜底

    实测（2026-09-16）：DDG news 偶发超时；且 region=cn-zh 查中文常返回 No results
    （DDG news 中文覆盖差）。故：原区域试 2 次 → 换 us-en 试 1 次 → 回落通用搜索。
    """
    from ddgs import DDGS
    region = region or detect_region(query)
    regions = [region] + (["us-en"] if region != "us-en" else [])
    for i, rg in enumerate(regions):
        for _ in range(2 if i == 0 else 1):
            try:
                with DDGS() as d:
                    r = list(d.news(query, region=rg, max_results=max_results))
                if r:
                    if rg != region:
                        sys.stderr.write(f"[warn] news 在 {region} 无结果，已用 {rg} 命中\n")
                    return r
            except Exception:
                continue
    sys.stderr.write("[warn] news 通道失败，回落通用搜索（无时效过滤）\n")
    return search_text(query, max_results, region=region)


def _opener(addheaders):
    import ssl
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    handlers = [urllib.request.HTTPSHandler(context=ctx)]
    if PROXY:
        handlers.insert(0, urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    op = urllib.request.build_opener(*handlers)
    op.addheaders = addheaders
    return op


def search_github(query, max_results=10):
    import urllib.parse
    op = _opener([("User-Agent", "workbuddy"), ("Accept", "application/vnd.github+json")])
    url = ("https://api.github.com/search/repositories?q="
           + urllib.parse.quote(query) + "&sort=stars&order=desc&per_page=" + str(max_results))
    with op.open(url, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8", "ignore"))
    out = []
    for it in d.get("items", []):
        out.append({
            "title": it["full_name"],
            "href": it["html_url"],
            "body": f"★{it['stargazers_count']} | " + (it.get("description") or ""),
        })
    return out


def fetch_page(url):
    """Jina Reader：任意 URL 转 LLM 友好 markdown"""
    op = _opener([("User-Agent", "Mozilla/5.0")])
    with op.open("https://r.jina.ai/" + url, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def _print(results):
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()
        href = (r.get("href") or r.get("url") or "").strip()
        body = (r.get("body") or r.get("snippet") or "").strip()
        print(f"[{i}] {title}")
        print(f"    {href}")
        if body:
            print(f"    {body[:200]}")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--news", action="store_true", help="新闻搜索")
    ap.add_argument("--github", action="store_true", help="GitHub 仓库搜索")
    ap.add_argument("--fetch", action="store_true", help="抓取网页正文")
    ap.add_argument("--region", default=None, help="搜索区域，默认按语种自动选（中文 cn-zh / 其他 us-en）")
    ap.add_argument("--raw", action="store_true", help="输出原始 JSON")
    ap.add_argument("--proxy-check", action="store_true", help="只打印代理探测结果后退出")
    ap.add_argument("--no-proxy", action="store_true", help="强制直连（代理假活时的自愈通道）")
    args = ap.parse_args()

    if args.proxy_check:
        print(f"代理：{PROXY or '直连（无可用代理）'}")
        return

    if args.fetch:
        print(fetch_page(args.query))
        return

    if not args.query:
        print(__doc__)
        return

    try:
        if args.github:
            results = search_github(args.query, args.n)
        elif args.news:
            results = search_news(args.query, args.n, region=args.region)
        else:
            results = search_text(args.query, args.n, region=args.region)
    except Exception as e:
        # 失败要给"下一步怎么办"，不要甩 traceback —— SOUL 要求回落时必须在产出里注明
        sys.stderr.write(f"[fail] 搜索通道失败（已重试）：{type(e).__name__}: {str(e)[:150]}\n")
        sys.stderr.write("[fallback] 按 SOUL.md「搜索来源偏好」改走 WebSearch 内置工具，并在产出中注明回落通道\n")
        sys.exit(2)

    if args.raw:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        _print(results)


if __name__ == "__main__":
    main()
