# -*- coding: utf-8 -*-
"""GitHub Actions 盘中池内快照 MVP v1（2026-08-28）
================================================================
吸收 niuone 实时更新方法论三项工程模式：
  1. fail-retain —— 任何异常只写 status 不写数据文件，workflow 见无 diff 即跳过 commit/deploy（旧快照永不丢失）
  2. freshness 预检 —— 行情时间戳非当日（节假日/休市）→ skip 不 patch；当日但滞后>90min → 标记 stale 仍如实 patch
  3. 显式 TZ —— 全部按 Asia/Shanghai 判定（GHA schedule 走 UTC，见 rt_snapshot.yml 注释换算）

链路：checkout main 池 JS（enhanced_data/short_pool/a5_pool）→ qt 批量行情 → patch chg/px/intraday
      → 成功才由 workflow commit+deploy（收盘 15:30 本地全量重建自动覆盖盘中字段，幂等无残留）

用法：
  python .github/probe/rt_snapshot.py            # 真实执行（写回三个 JS）
  python .github/probe/rt_snapshot.py --dry-run  # 干跑：解析+拉取+patch 仅内存，不写盘
退出码恒 0（fail-retain：错误只记录在 snapshot_status.json 的 warn 字段）
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

CN = timezone(timedelta(hours=8), name="Asia/Shanghai")
PROBE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(PROBE_DIR))  # .github/probe -> .github -> repo root
FILES = ["enhanced_data.js", "short_pool.js", "a5_pool.js"]
STATUS_PATH = os.path.join(PROBE_DIR, "snapshot_status.json")
QT_BATCH = 50
STALE_MIN = 90


def now_cn():
    return datetime.now(CN)


def load_js(name):
    path = os.path.join(REPO, name)
    txt = open(path, encoding="utf-8").read()
    m = re.match(r"^window\.\w+\s*=\s*", txt)
    prefix = m.group(0) if m else ""
    obj = json.loads(txt[len(prefix):].rstrip().rstrip(";"))
    return path, prefix, obj


def save_js(path, prefix, obj):
    body = prefix + json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    open(path, "w", encoding="utf-8").write(body + "\n")


def to_qt_code(code):
    """6 位无前缀 code → qt 前缀代码（6/9→sh，3/0→sz，4/8→bj）"""
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code[:1] in ("6", "9"):
        return "sh" + code
    if code[:1] in ("0", "3", "2"):
        return "sz" + code
    return "bj" + code


def fetch_qt(codes):
    out, ts_fields = {}, []
    for i in range(0, len(codes), QT_BATCH):
        chunk = [to_qt_code(c) for c in codes[i:i + QT_BATCH]]
        url = "https://qt.gtimg.cn/q=" + ",".join(chunk)
        body = urllib.request.urlopen(url, timeout=25).read().decode("gbk", errors="replace")
        for line in body.split(";"):
            m = re.search(r'="(.*)"', line.strip())
            if not m:
                continue
            f = m.group(1).split("~")
            if len(f) < 5:
                continue
            try:
                px, prev = float(f[3]), float(f[4])
            except (TypeError, ValueError):
                continue
            if prev <= 0:
                continue
            out[f[2]] = {"px": px, "chg": round((px / prev - 1) * 100, 2)}
            if len(f) > 30 and re.match(r"^\d{14}$", f[30]):
                ts_fields.append(f[30])
    quote_ts = max(ts_fields) if ts_fields else None
    return out, quote_ts


def main():
    dry = "--dry-run" in sys.argv
    status = {"ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "dry_run": dry, "ok": False, "warn": "", "patched": {}, "n_quotes": 0}
    try:
        objs = {}
        for name in FILES:
            p, pre, o = load_js(name)
            objs[name] = (p, pre, o)

        # 1) 收集池内 codes（ENH/SHORT details 键 + A5 三清单）
        enh, short, a5 = objs["enhanced_data.js"][2], objs["short_pool.js"][2], objs["a5_pool.js"][2]
        codes = set(enh.get("details", {}).keys())
        codes |= set(short.get("details", {}).keys())
        for lst_name in ("watchlist", "avoid", "positions"):
            for it in a5.get(lst_name, []) or []:
                c = it.get("code")
                if c:
                    codes.add(c)
        codes = sorted(codes)
        status["n_codes"] = len(codes)

        # 2) qt 批量拉取 + freshness 预检
        quotes, quote_ts = fetch_qt(codes)
        status["n_quotes"] = len(quotes)
        if not quotes:
            raise RuntimeError("qt 行情 0 条，视为上游失败（fail-retain 保留旧快照）")
        if quote_ts:
            q_dt = datetime.strptime(quote_ts, "%Y%m%d%H%M%S").replace(tzinfo=CN)
            if q_dt.date() < now_cn().date():
                status["ok"] = True
                status["warn"] = f"skip: 行情日期 {q_dt.date()} < 今日，市场休市/未开盘，不 patch"
                json.dump(status, open(STATUS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print("SKIP:", status["warn"])
                return 0
            if (now_cn() - q_dt).total_seconds() / 60 > STALE_MIN:
                status["warn"] = f"stale: 行情时间 {q_dt.strftime('%H:%M')} 滞后>{STALE_MIN}min，仍如实 patch"
            status["quote_ts_cn"] = q_dt.strftime("%Y-%m-%d %H:%M:%S")
            ts_hhmm = q_dt.strftime("%H:%M")
        else:
            ts_hhmm = now_cn().strftime("%H:%M")
            status["warn"] = "stale: 行情时间戳缺失，用当前时间标记"

        # 3) patch chg/px（ENH+SHORT details；A5 三清单只 patch chg）
        n_enh = n_short = n_a5 = 0
        for c, q in quotes.items():
            c6 = c[-6:]
            if c6 in enh.get("details", {}):
                enh["details"][c6]["px"] = q["px"]
                enh["details"][c6]["chg"] = q["chg"]
                n_enh += 1
            if c6 in short.get("details", {}):
                short["details"][c6]["px"] = q["px"]
                short["details"][c6]["chg"] = q["chg"]
                n_short += 1
        note = f"{now_cn().strftime('%Y-%m-%d')} 盘中行情（{ts_hhmm}）· 分数为收盘口径"
        enh.setdefault("meta", {})["intraday"] = note
        enh["meta"]["intraday_ts"] = ts_hhmm
        short["intraday"] = note
        short["intraday_ts"] = ts_hhmm
        for lst_name in ("watchlist", "avoid", "positions"):
            for it in a5.get(lst_name, []) or []:
                c = it.get("code")
                if not c:
                    continue
                c6 = c[-6:] if len(c) > 6 else c  # A5 清单 code 带 sh/sz 前缀，quotes 键为 6 位
                if c6 in quotes:
                    it["chg"] = quotes[c6]["chg"]
                    n_a5 += 1
        a5["intraday"] = True
        a5["intraday_ts"] = ts_hhmm
        status["patched"] = {"enh": n_enh, "short": n_short, "a5": n_a5}

        # 4) 写盘（fail-retain：只有走到这里才写）
        if dry:
            status["ok"] = True
            print("DRY-RUN OK:", json.dumps(status["patched"], ensure_ascii=False))
        else:
            for name in FILES:
                p, pre, o = objs[name]
                save_js(p, pre, o)
            status["ok"] = True
            print("PATCHED:", json.dumps(status["patched"], ensure_ascii=False),
                  "| quote_ts:", status.get("quote_ts_cn", "?"), "|", status.get("warn", "fresh"))
        json.dump(status, open(STATUS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return 0
    except Exception as exc:
        status["ok"] = False
        status["warn"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        json.dump(status, open(STATUS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("FAIL-RETAIN:", status["warn"])
        return 0  # 恒 0：workflow 以 git diff 判定是否 commit/deploy


if __name__ == "__main__":
    sys.exit(main())
