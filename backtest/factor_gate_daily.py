# -*- coding: utf-8 -*-
"""四检查日链闸（R-gatewiring-0918）——只跑便宜且高信号的两项
  1) warmup-check 于 panel_kv_0913.npz（只读 mask，~10MB）
  2) finite-check 于日链产出的状态 JSON（数字叶子扫 inf/NaN）
退出码：仅 FAIL 时非零；WARN 不影响。挂 daily_refresh.py STEPS 的 [软] 步。
用法：python backtest/factor_gate_daily.py [额外状态文件...]
"""
import json, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # 2026-09-24 云端可移植（原写死 D:/…，本机解析恒等）
sys.path.insert(0, str(BASE / "backtest"))
import factor_gate as fg

PANEL_KV = BASE / "backtest" / "kv_resonance_0913" / "panel_kv_0913.npz"
STATE_TARGETS = [
    "backtest/satellite_paper.json", "backtest/satellite_paper_b.json",
    "backtest/gold_sat_paper.json", "backtest/a5_paper_state.json",
    "backtest/paper_state.json", "backtest/pct40_exits_state.json",
    "backtest/exit_control_state.json", "backtest/khunter_paper_state.json",
]

def scan_json(obj, path="", out=None):
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            scan_json(v, path + "/" + str(k), out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            scan_json(v, path + "[%d]" % i, out)
    elif isinstance(obj, float):
        if obj != obj:
            out.append((path, "nan"))
        elif obj in (float("inf"), float("-inf")):
            out.append((path, "inf"))
    return out

def main():
    extra = [a for a in sys.argv[1:] if not a.startswith("-")]
    targets = STATE_TARGETS + extra
    fails, warns = [], []
    print("=== [1/2] warmup-check ===")
    if PANEL_KV.exists():
        r = fg.warmup_check(str(PANEL_KV))
        print("  %s | min=%d median=%d gt0_share=%.2f implied_warmup=%d"
              % (r["verdict"], r["min"], r["median"], r["gt0_share"], r["implied_warmup_days"]))
        if r["verdict"] == "WARN":
            warns.append("warmup: " + r["note"])
    else:
        print("  SKIP（面板不存在）")
    print("=== [2/2] finite-check（状态 JSON 数字叶子）===")
    nchk = 0
    for rel in targets:
        cand = [Path(rel)]
        if not Path(rel).is_absolute():
            cand.append(BASE / rel)
        p = next((c for c in cand if c.exists()), None)
        if p is None:
            continue
        nchk += 1
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            fails.append("%s 读取失败 %s" % (rel, e))
            print("  FAIL  %s 读取失败 %s" % (rel, e))
            continue
        bad = scan_json(d)
        if bad:
            fails.append("%s: %d 个非有限值，样例 %s" % (rel, len(bad), bad[:3]))
            print("  FAIL  %s -> %d 个非有限值（样例 %s）" % (rel, len(bad), bad[:3]))
        else:
            print("  PASS  %s" % rel)
    print("  受检文件 %d 个" % nchk)
    for w in warns:
        print("  WARN:", w)
    verdict = "FAIL" if fails else ("WARN" if warns else "PASS")
    print("[gate] %s | FAIL=%d WARN=%d" % (verdict, len(fails), len(warns)))
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())
