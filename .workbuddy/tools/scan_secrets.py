# -*- coding: utf-8 -*-
"""敏感信息扫描：找出不能上云的文件。只读，不改任何东西。"""
import os, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PATTERNS = [
    ("飞书 appSecret", re.compile(r"[0-9A-Za-z]{24,40}")),
    ("通用 secret", re.compile(r"(?i)(secret|token|apikey|api_key|password|passwd|access_key)\s*[:=]\s*[\"']?([A-Za-z0-9_\-]{16,})")),
    ("Ark/OpenAI key", re.compile(r"\b(ark-|sk-)[A-Za-z0-9\-]{10,}")),
    ("GitHub token", re.compile(r"\bghp_[A-Za-z0-9]{20,}")),
    ("私钥", re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")),
    ("飞书 open_id", re.compile(r"\bou_[a-f0-9]{16,}")),
]

# 只扫"规则/身份/配置"这类会被同步的文件；不扫 projects/logs（体积大且含会话全文）
TARGETS = [
    r"C:\Users\Admin\.workbuddy\SOUL.md",
    r"C:\Users\Admin\.workbuddy\IDENTITY.md",
    r"C:\Users\Admin\.workbuddy\USER.md",
    r"C:\Users\Admin\.workbuddy\MEMORY.md",
    r"C:\Users\Admin\.workbuddy\AGENTS.md",
    r"C:\Users\Admin\.workbuddy\settings.json",
    r"C:\Users\Admin\.workbuddy\mcp.json",
    r"C:\Users\Admin\.workbuddy\models.json",
    r"C:\Users\Admin\.workbuddy\认知盲区双轨框架.md",
    r"C:\Users\Admin\.workbuddy\认知盲区证据台账.md",
]
DIRS = [
    r"C:\Users\Admin\WorkBuddy\20260409211929\.workbuddy",
]

SECRET_LITERAL = re.compile(r"appSecret|app_secret|AppSecret")

def scan_file(p):
    hits = []
    try:
        t = open(p, encoding="utf-8", errors="replace").read()
    except Exception:
        return hits
    # 只关心"看起来真有值"的
    for i, line in enumerate(t.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        if SECRET_LITERAL.search(s) or "clientSecret" in s or "apiKey" in s:
            hits.append((i, "疑似密钥字段", s[:120]))
            continue
        m = re.search(r"\b(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9\-]{16,}|ark-[A-Za-z0-9\-]{16,})\b", s)
        if m:
            hits.append((i, "密钥值", s[:120]))
    return hits

print("=== 敏感信息扫描（规则 / 身份 / 配置文件）===")
total = 0
for p in TARGETS:
    if not os.path.exists(p):
        print("  [缺失] %s" % p)
        continue
    h = scan_file(p)
    if h:
        total += len(h)
        print("  ⚠ %s  (%d 处)" % (p, len(h)))
        for ln, kind, s in h[:6]:
            print("      L%-4d %s | %s" % (ln, kind, s))
    else:
        print("  ok %s" % p)

print()
for d in DIRS:
    print("=== 目录扫描 %s ===" % d)
    n = 0
    for dp, dn, fn in os.walk(d):
        for f in fn:
            if not f.lower().endswith((".md", ".json", ".txt", ".py", ".env")):
                continue
            p = os.path.join(dp, f)
            h = scan_file(p)
            if h:
                n += len(h)
                print("  ⚠ %s (%d 处)" % (p.replace(d, "..."), len(h)))
                for ln, kind, s in h[:4]:
                    print("      L%-4d %s | %s" % (ln, kind, s))
            if n > 20:
                break
    if n == 0:
        print("  ok 未发现明文密钥字段")

print()
print("总计可疑处：%d" % (total + n))
