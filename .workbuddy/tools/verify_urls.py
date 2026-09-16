#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_urls.py — 来源验证标注门禁工具（v1.0, 2026-09-14）
用途：URL 写进交付物标 ✅ 之前，先跑本工具取得验证证据。
用法：
  python verify_urls.py <url1> <url2> ...          # 走系统代理
  python verify_urls.py --direct <url1> ...        # 绕代理直连
输出：每个 URL 的 HTTP 状态 / 页面标题 / Last-Modified / 自动生成的标注建议
规则：200 + 有标题 => 建议标 ✅[curl实测+日期]；否则 => 建议标 ⚠️
"""
import sys, re, ssl, json, urllib.request, urllib.error
from datetime import date

def fetch(url: str, direct: bool, timeout: int = 15) -> dict:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    if direct:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                             urllib.request.HTTPSHandler(context=ctx))
    else:
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/123.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    try:
        with opener.open(req, timeout=timeout) as r:
            body = r.read(200_000).decode("utf-8", errors="replace")
            return {"status": r.status, "last_modified": r.headers.get("Last-Modified", "-"), "body": body}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "last_modified": "-", "body": ""}
    except Exception as e:
        return {"status": f"ERR:{type(e).__name__}", "last_modified": "-", "body": ""}

def main():
    args = sys.argv[1:]
    direct = "--direct" in args
    urls = [a for a in args if not a.startswith("--")]
    if not urls:
        print(__doc__); sys.exit(1)
    today = date.today().isoformat()
    results = []
    for u in urls:
        r = fetch(u, direct)
        title = ""
        m = re.search(r"<title[^>]*>([^<]{1,200})", r["body"], re.I)
        if m: title = m.group(1).strip()
        ok = (r["status"] == 200) and bool(title)
        tag = (f'✅[curl {r["status"]}+标题"{title[:40]}", {today}]' if ok
               else f'⚠️[curl {r["status"]}, 无标题或不可达, {today} — 禁止标✅]')
        results.append({"url": u, "status": r["status"], "title": title,
                        "last_modified": r["last_modified"], "建议标注": tag})
        print(f'{"="*70}\nURL: {u}\n状态: {r["status"]}  |  Last-Modified: {r["last_modified"]}\n标题: {title}\n建议标注: {tag}')
    with open("verify_urls_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n证据已落盘: verify_urls_result.json（{today}）——交付物对账时引用此文件")

if __name__ == "__main__":
    main()
