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
    # ① 今日在榜
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
    # ② 老 pending → 正式：隔日无论是否仍在榜一律转正式（2026-08-19）
    for code in list(old_pending.keys()):
        if code in track:
            continue
        if code not in pending:
            continue
        pe = pending[code]
        track[code] = {"entry": today, "last_seen": today, "exit": _exit(today),
                       "status": "active", "pool": pe.get("pool", "")}
        pending.pop(code, None)
    return track, pending


ok = True
# 场景1（2026-08-19 新语义）：A 昨天新上榜进 pending，今天掉榜（不在池）→ 仍要转正式（进池=默认买，须跟踪卖出）
t0, p0 = simulate({"B": {"entry": "2026-08-16"}}, {"A": {"entry_candidate": "2026-08-17", "first_seen": "2026-08-17", "pool": "主板"}},
                  {"B"}, {"B"}, "2026-08-18")
ok1 = ("A" in t0) and (t0["A"]["entry"] == "2026-08-18") and ("A" not in p0)
ok &= ok1
print("场景1 掉榜隔日也转正式: 正式池含A =", "A" in t0, "(应True) | entry =", t0.get("A", {}).get("entry"), "(应2026-08-18) | pending清 =", "A" not in p0, "(应True) |", "OK" if ok1 else "FAIL")

# 场景2：B 已在正式池，C 今天新上榜 → C 进 pending 不入正式池（当日不入，隔日转正）
t2, p2 = simulate({"B": {"entry": "2026-08-16"}}, {}, {"B"}, {"B", "C"}, "2026-08-18")
ok2 = ("C" not in t2) and ("C" in p2)
ok &= ok2
print("场景2 新上C入pending: 正式池含C =", "C" in t2, "(应False) | pending含C =", "C" in p2, "(应True) |", "OK" if ok2 else "FAIL")

# 场景3：B 掉榜后重新上榜 → 刷新 entry/last_seen/exit
t3, p3 = simulate({"B": {"entry": "2026-08-10", "last_seen": "2026-08-16"}}, {}, {}, {"B"}, "2026-08-18")
ok3 = (t3["B"]["entry"] == "2026-08-18" and t3["B"]["last_seen"] == "2026-08-18"
       and t3["B"]["exit"] == _exit("2026-08-18"))
ok &= ok3
print("场景3 重新上榜刷新: entry =", t3["B"]["entry"], "(应08-18) | last_seen =", t3["B"]["last_seen"],
      "| exit =", t3["B"]["exit"], "(应", _exit("2026-08-18") + ")", "|", "OK" if ok3 else "FAIL")

print("=== 全部通过 OK ===" if ok else "=== 有失败 FAIL ===")
