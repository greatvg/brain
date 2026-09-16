#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
check_rules.py - 规则一致性检查器（防错机制 B 主干，2026-09-16 建立）

背景：2026-09-16 发现三处规则互相矛盾（C1 搜索通道 / C2 记忆写入 / C3 代理端口），
根因是「规则系统是手抄本而非引用制」——同一规则多处副本、易腐值写死、无机器核验。
本工具把核验从"靠自觉"升级为"机器扫"。

四类检测：
  ① 跨文件重复   近似复制的句子在多份文件中出现（n-gram Jaccard）
  ② 结论冲突     同一对象在不同文件被判相反结论（正/负极性并存）
  ③ 易腐值硬编码 端口 / 密钥 / 会话级绝对路径 / open_id 等会过期或泄漏的值
  ④ 超期未复核   带日期的规则标题超过 90 天

定位：规则文件（SOUL.md / 工作区 MEMORY.md / 用户级 MEMORY.md）
原则：只告警，不自动改。裁决权在荣总。

用法：
  python check_rules.py                 # 全量检查
  python check_rules.py --json out.json # 同时落盘 JSON 报告
  python check_rules.py --ws <工作区>   # 手动指定工作区（默认从 cwd 向上找）
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOME = Path.home()

# ---------------------------------------------------------------- 文件定位


def locate_files(ws_arg: str | None = None) -> list[tuple[str, Path, str]]:
    """返回 [(标签, 路径, 正文)]，缺失的文件跳过。"""
    cands: list[tuple[str, Path]] = [
        ("SOUL.md", HOME / ".workbuddy" / "SOUL.md"),
        ("USER-MEMORY.md", HOME / ".workbuddy" / "MEMORY.md"),
    ]

    # 工作区 MEMORY：显式参数 > 环境变量 > 从 cwd 向上找
    ws = ws_arg or os.environ.get("WORKBUDDY_WS")
    roots = [Path(ws)] if ws else []
    p = Path.cwd()
    roots += [p] + list(p.parents)
    for base in roots:
        cand = base / ".workbuddy" / "memory" / "MEMORY.md"
        if cand.exists():
            cands.append(("WS-MEMORY.md", cand))
            break

    out = []
    for label, path in cands:
        if path.exists():
            out.append((label, path, path.read_text(encoding="utf-8", errors="ignore")))
    return out


# ---------------------------------------------------------------- ① 跨文件重复

STRIP_PREFIX = re.compile(r"^[#>\-\*\+\d\.\)\]]+\s*")
STRIP_MARK = re.compile(r"\*\*|`|~~|\[|\]")


SUPERSEDED_RE = re.compile(r"\[superseded\]", re.I)


def superseded_lines(text: str) -> set[int]:
    """标记 [superseded] 存档区的行号（从该标题到下一个标题）。

    新陈代谢机制的一部分：被新结论取代的旧规则**保留存档**（不物理删除），
    但它已不生效，因此不得参与「重复/冲突/易腐值」判定——否则会误报。
    """
    out: set[int] = set()
    in_super = False
    for i, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if re.match(r"^#{1,6}\s", s):
            in_super = bool(SUPERSEDED_RE.search(s))
            if in_super:
                out.add(i)
            continue
        if in_super:
            out.add(i)
    return out


def split_sentences(text: str) -> list[tuple[int, str]]:
    """切句 → [(行号, 句子)]，跳过短句/格式行/标题行/[superseded] 存档区。"""
    skip = superseded_lines(text)
    out = []
    for i, raw in enumerate(text.splitlines(), 1):
        if i in skip:
            continue
        line = raw.strip()
        if not line or line.startswith("---") or line.startswith("|") or line.startswith("#"):
            continue
        line = STRIP_PREFIX.sub("", line)
        line = STRIP_MARK.sub("", line)
        for s in re.split(r"[。；;！!？?]", line):
            s = s.strip()
            if len(s) >= 14:
                out.append((i, s))
    return out


def ngrams(s: str, n: int = 4) -> set[str]:
    s = re.sub(r"\s+", "", s)
    return {s[i : i + n] for i in range(max(0, len(s) - n + 1))}


def jaccard(a: str, b: str) -> float:
    A, B = ngrams(a), ngrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def check_duplicates(files, threshold: float = 0.55):
    """跨文件近似复制句检测（同一文件内不算）。"""
    found = []
    sents = {label: split_sentences(text) for label, _, text in files}
    labels = [f[0] for f in files]
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            la, lb = labels[i], labels[j]
            for lna, sa in sents[la]:
                A = ngrams(sa)
                for lnb, sb in sents[lb]:
                    # 粗筛：两串长度差 40% 以上直接跳过
                    if min(len(sa), len(sb)) / max(len(sa), len(sb)) < 0.6:
                        continue
                    score = jaccard(sa, sb)
                    if score >= threshold:
                        found.append(
                            {
                                "score": round(score, 3),
                                "a": f"{la}:{lna}",
                                "b": f"{lb}:{lnb}",
                                "text_a": sa[:90],
                                "text_b": sb[:90],
                            }
                        )
    # 只保留每个交集的最相似一条，降噪
    found.sort(key=lambda x: -x["score"])
    seen, out = set(), []
    for f in found:
        key = (f["a"], f["b"])
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


# ---------------------------------------------------------------- ② 结论冲突

TOPICS = [
    ("搜索通道", ["搜索", "Google", "谷歌", "Bing", "DuckDuckGo", "ddgs", "agent-browser"]),
    ("记忆写入", ["记忆写入", "自动写", "自动记忆", "存档", "确认后才写", "不主动写"]),
    ("代理/端口", ["代理", "127.0.0.1:", "proxy", "端口"]),
    ("飞书调用身份", ["--as bot", "--as user", "lark-cli", "profile"]),
]

# 参与冲突判定的对象（一个对象被判相反结论 = 冲突）
OBJECTS = [
    "Google",
    "谷歌",
    "Bing",
    "DuckDuckGo",
    "ddgs",
    "agent-browser",
    "search_web.py",
    "自动写入",
    "确认后才写",
    "63281",
    "7790",
    "56476",
    "--as bot",
    "--as user",
]

# 极性词：否定优先于肯定。"可用" 会误匹配 "不可用"，故改用更明确的表述。
POL_POS = ["优先", "第一通道", "主通道", "必须用", "推荐用", "默认", "已验证", "实测可用"]
POL_NEG = ["已废", "废了", "已关", "关闭", "不可用", "不能用", "失效", "弃用", "不要用", "拦截", "作废", "过期", "停用"]


def check_conflicts(files):
    """同一主题下，同一对象同时存在正/负极性结论 = 冲突候选。"""
    topics_hits = {}
    for topic, kws in TOPICS:
        hits = []
        for label, _, text in files:
            for ln, s in split_sentences(text):
                if any(k.lower() in s.lower() for k in kws):
                    hits.append((label, ln, s))
        if hits:
            topics_hits[topic] = hits

    conflicts = []
    for topic, hits in topics_hits.items():
        polar = {}
        for label, ln, s in hits:
            low = s.lower()
            # 否定优先：避免 "不可用" 被 "可用" 误判为正向
            pol = "neg" if any(w in s for w in POL_NEG) else ("pos" if any(w in s for w in POL_POS) else None)
            if not pol:
                continue
            for o in OBJECTS:
                if o.lower() in low:
                    polar.setdefault(o, {}).setdefault(pol, []).append(f"{label}:{ln}")
        for obj, bypol in polar.items():
            if "pos" in bypol and "neg" in bypol:
                conflicts.append(
                    {
                        "topic": topic,
                        "object": obj,
                        "pos_refs": bypol["pos"][:3],
                        "neg_refs": bypol["neg"][:3],
                    }
                )
    return conflicts, topics_hits


# ---------------------------------------------------------------- ③ 易腐值硬编码

FROZEN = [
    ("本机端口", r"(?:127\.0\.0\.1|localhost)[:/](\d{2,5})", "HIGH", "端口会随会话漂移，应改为动态探测"),
    ("远程调试端口", r"remote-debugging-port=(\d+)", "HIGH", "会话级参数，应改为动态取值"),
    ("密钥片段", r"\b(ark-[A-Za-z0-9\-]{6,}|sk-[A-Za-z0-9\-]{6,}|ghp_[A-Za-z0-9]{6,})", "HIGH", "密钥不得落盘，须脱敏"),
    ("open_id / app_id", r"\b(ou_[a-f0-9]{12,}|cli_[a-z0-9]{8,})", "MED", "身份标识易变，建议改为运行时获取"),
    ("会话级路径", r"[A-Za-z]:\\+Users\\+[^\\\s`|\"'）)]{4,}", "HIGH", "工作区/用户目录会随机器变，应写动态定位方式"),
    ("项目数据路径", r"[A-Za-z]:\\+(?!Users)[^\\\s`|\"'）)]{3,}", "LOW", "项目资产位置，变动时需同步更新"),
]


def check_frozen(files):
    out = []
    for label, _, text in files:
        for i, raw in enumerate(text.splitlines(), 1):
            for name, pat, level, advice in FROZEN:
                for m in re.finditer(pat, raw):
                    val = m.group(1) if m.groups() else m.group(0)
                    out.append(
                        {
                            "level": level,
                            "kind": name,
                            "file": label,
                            "line": i,
                            "value": val[:60],
                            "advice": advice,
                        }
                    )
    return out


# ---------------------------------------------------------------- ④ 超期未复核

DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
REVIEW_DAYS = 90


def check_stale(files):
    today = date.today()
    out = []
    for label, _, text in files:
        skip = superseded_lines(text)
        for i, raw in enumerate(text.splitlines(), 1):
            if i in skip:
                continue
            if not raw.lstrip().startswith("#"):
                continue
            m = DATE_RE.search(raw)
            if not m:
                continue
            try:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            days = (today - d).days
            if days > REVIEW_DAYS:
                out.append(
                    {
                        "file": label,
                        "line": i,
                        "age_days": days,
                        "title": raw.strip()[:70],
                    }
                )
    out.sort(key=lambda x: -x["age_days"])
    return out


# ---------------------------------------------------------------- 主流程


def main():
    ap = argparse.ArgumentParser(description="规则一致性检查器")
    ap.add_argument("--json", metavar="PATH", help="同时输出 JSON 报告到指定路径")
    ap.add_argument("--ws", metavar="DIR", help="手动指定工作区目录")
    ap.add_argument("--threshold", type=float, default=0.55, help="重复检测相似度阈值，默认 0.55")
    args = ap.parse_args()

    files = locate_files(args.ws)
    if not files:
        print("未找到任何规则文件，检查路径。")
        return 1

    # 防"假绿"：工作区 MEMORY 靠 cwd 向上定位，换个目录跑就会静默漏掉它，
    # 而重复/冲突/易腐值恰恰大量集中在这个文件里 —— 必须显式告警，不能安静降级。
    labels = {l for l, _, _ in files}
    if "WS-MEMORY.md" not in labels:
        print("!" * 66)
        print("[警告] 未定位到工作区 MEMORY.md —— 本次为**部分扫描**，不得当作通过！")
        print("  定位方式：cwd 向上找 .workbuddy/memory/MEMORY.md")
        print("  修法：cd 到工作区目录，或 --ws <工作区目录>，或设 WORKBUDDY_WS 环境变量")
        print("!" * 66)
        print()

    print("=" * 66)
    print("规则一致性检查 — " + datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 66)
    for label, path, text in files:
        print(f"  [{label}] {len(text):>6d} 字符 / {text.count(chr(10)) + 1:>4d} 行  {path}")
    sup = {l: len(superseded_lines(t)) for l, _, t in files}
    if any(sup.values()):
        detail = " / ".join(f"{k} {v} 行" for k, v in sup.items() if v)
        print(f"  [superseded 存档区] {detail} —— 已豁免检测（存档不生效，不算冲突）")
    print()

    dups = check_duplicates(files, args.threshold)
    print(f"① 跨文件重复：{len(dups)} 组（阈值 {args.threshold}）")
    for d in dups[:12]:
        print(f"  [{d['score']}] {d['a']}  <->  {d['b']}")
        print(f"        A: {d['text_a']}")
        print(f"        B: {d['text_b']}")
    if len(dups) > 12:
        print(f"  ... 另有 {len(dups) - 12} 组（见 JSON）")
    print()

    conflicts, topics_hits = check_conflicts(files)
    total_topic_sents = sum(len(v) for v in topics_hits.values())
    print(f"② 结论冲突：{len(conflicts)} 处（主题覆盖 {len(topics_hits)} 个 / 命中句 {total_topic_sents} 条）")
    for c in conflicts:
        print(f"  ! [{c['topic']}] 对象「{c['object']}」被判相反结论：")
        print(f"      正向: {', '.join(c['pos_refs'])}")
        print(f"      负向: {', '.join(c['neg_refs'])}")
    print()

    frozen = check_frozen(files)
    by_level = {"HIGH": [], "MED": [], "LOW": []}
    for f in frozen:
        by_level[f["level"]].append(f)
    print(f"③ 易腐值硬编码：HIGH {len(by_level['HIGH'])} / MED {len(by_level['MED'])} / LOW {len(by_level['LOW'])}")
    kind_count = {}
    for f in frozen:
        k = (f["level"], f["kind"])
        kind_count[k] = kind_count.get(k, 0) + 1
    for (level, kind), n in sorted(kind_count.items()):
        print(f"  {level:5s} {kind:12s} {n:>3d} 处")
    for f in by_level["HIGH"][:8]:
        print(f"  HIGH -> {f['file']}:{f['line']}  {f['kind']} = {f['value']}")
    print()

    stale = check_stale(files)
    print(f"④ 规则年龄提示（标题带日期 >{REVIEW_DAYS} 天 —— 仅提示复核，不判违规）：{len(stale)} 条")
    for s in stale[:10]:
        print(f"  {s['age_days']:>4d} 天  {s['file']}:{s['line']}  {s['title']}")
    print()

    summary = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "partial": "WS-MEMORY.md" not in labels,
        "files": [{"label": l, "path": str(p), "chars": len(t), "lines": t.count("\n") + 1} for l, p, t in files],
        "duplicates": dups,
        "conflicts": conflicts,
        "frozen_high": len(by_level["HIGH"]),
        "frozen_med": len(by_level["MED"]),
        "frozen_low": len(by_level["LOW"]),
        "frozen_detail": frozen,
        "stale": stale,
    }
    if args.json:
        Path(args.json).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 报告已写入：{args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
