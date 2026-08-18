# -*- coding: utf-8 -*-
"""隔离单测：短线跟踪池「隔日入池 + 三时间」核心逻辑（与中长线 track_v9 一致）"""
import pandas as pd


def _exit(e):
    return str((pd.Timestamp(e) + pd.Timedelta(days=30)).date())


def simulate(old_track, old_pending, old_tiers_codes, today_codes, today):
    track = dict(old_track)
    pending = dict(old_pending)
    for c, rec in list(track.items()):
        rec.setdefault("exit", _exit(rec.get("entry", today)))
        rec.setdefault("status", "active")
        rec.setdefault("last_seen", rec.get("last_seen") or today)
    for code in today_codes:
        rec = track.get(code)
        if rec is not None:
            if code not in old_tiers_codes:
                rec["entry"] = today
                rec["exit"] = _exit(today)
            rec["last_seen"] = today
            rec["status"] = "active"
            pending.pop(code, None)
        else:
            pe = pending.get(code)
            if pe is not None:
                track[code] = {"entry": today, "last_seen": today, "exit": _exit(today),
                               "status": "active", "pool": pe.get("pool", "")}
                pending.pop(code, None)
            else:
                pending[code] = {"entry_candidate": today, "first_seen": today,
                                 "pool": "主板", "last": {"score": 90}}
    return track, pending


ok = True
# 场景1：B 已在正式池（entry=08-16），A 今天新上榜 → A 进 pending 不入正式池
t0, p0 = simulate({"B": {"entry": "2026-08-16"}}, {}, {"B"}, {"B", "A"}, "2026-08-18")
ok1 = ("A" not in t0) and ("A" in p0) and ("B" in t0)
ok &= ok1
print("场景1 新上A入pending: 正式池含A =", "A" in t0, "(应False) | pending含A =", "A" in p0, "(应True) |", "OK" if ok1 else "FAIL")

# 场景2：A 昨天 pending 今天仍在榜 → 转正式 entry=今天
t1, p1 = simulate({"B": {"entry": "2026-08-16"}},
                  {"A": {"entry_candidate": "2026-08-17", "first_seen": "2026-08-17", "pool": "主板"}},
                  {"B"}, {"B", "A"}, "2026-08-18")
ok2 = ("A" in t1) and (t1["A"]["entry"] == "2026-08-18") and ("A" not in p1)
ok &= ok2
print("场景2 pending隔日转正: 正式池含A =", "A" in t1, "(应True) | entry =", t1.get("A", {}).get("entry"), "(应2026-08-18) | pending清 =", "A" not in p1, "(应True) |", "OK" if ok2 else "FAIL")

# 场景3：B 掉榜后重新上榜 → 刷新 entry/last_seen/exit
t2, p2 = simulate({"B": {"entry": "2026-08-10", "last_seen": "2026-08-16"}}, {}, {}, {"B"}, "2026-08-18")
ok3 = (t2["B"]["entry"] == "2026-08-18" and t2["B"]["last_seen"] == "2026-08-18"
       and t2["B"]["exit"] == _exit("2026-08-18"))
ok &= ok3
print("场景3 重新上榜刷新: entry =", t2["B"]["entry"], "(应08-18) | last_seen =", t2["B"]["last_seen"],
      "| exit =", t2["B"]["exit"], "(应", _exit("2026-08-18") + ")", "|", "OK" if ok3 else "FAIL")

print("=== 全部通过 OK ===" if ok else "=== 有失败 FAIL ===")
