# -*- coding: utf-8 -*-
"""面板刷新器（2026-09-17 建）——factorlab 面板 + oss 面板重建（生产轨B/影子轨共用数据源）

根因：面板（panel_0913.pkl / oss_panel_0913.pkl）由专用构建器生成，但**从不被日链刷新**；
      val_em 主表停在 09-11 → 面板停在 09-11 → 生产轨 B 目标清单冻结（asof 谎报 09-16）。
本脚本：备份旧面板（单代 .bak）→ 依次跑两个构建器 → 验证（末日==index_000300 末日、因子覆盖、ND 增长）。
用法：python backtest/rebuild_panels.py
"""
import shutil, subprocess, sys, time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent   # 2026-09-24 云端可移植：原写死 D:/…（云端无 D 盘）
PY = r"C:/Users/Admin/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
if not Path(PY).exists():                       # 云端无此解释器 → 退回当前解释器（本机行为不变）
    PY = sys.executable
FL = BASE / "backtest" / "factorlab_0913" / "panel_0913.pkl"
OSSP = BASE / "backtest" / "oss_0913" / "oss_panel_0913.pkl"
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

def run(script):
    t = time.time()
    r = subprocess.run([PY, str(script)], cwd=str(script.parent), capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = "\n".join((r.stdout or "").strip().splitlines()[-6:])
    log(f"[{script.name}] rc={r.returncode} 耗时 {time.time()-t:.0f}s")
    if tail:
        for ln in tail.splitlines():
            log(f"   | {ln[:140]}")
    if r.returncode != 0:
        err = "\n".join((r.stderr or "").strip().splitlines()[-8:])
        log(f"[ABORT] {script.name} 失败：\n{err}")
        sys.exit(1)

# 守卫：面板末日 == index 末日 → 已最新，跳过
import pandas as _pd
_idx = _pd.read_csv(BASE / "index_000300.csv", parse_dates=["date"])
_expect = _idx["date"].dt.strftime("%Y-%m-%d").max()
import pickle as _pk
if OSSP.exists():
    with open(OSSP, "rb") as _fh:
        _p = _pk.load(_fh)
    _last = str(_p["cal"][-1])[:10]
    del _p
    if _last == _expect:
        log(f"[skip] 面板已最新（末日 {_last} == 日历末日）——无需重建")
        sys.exit(0)
    log(f"[需要重建] 面板末日 {_last} < 日历末日 {_expect}")

# 备份（单代）
for p in (FL, OSSP):
    if p.exists():
        bak = p.with_suffix(".pkl.bak")
        shutil.copy2(p, bak)
        log(f"[备份] {p.name} → {bak.name}（{p.stat().st_size/2**20:.0f}MB）")

run(BASE / "backtest" / "factorlab_0913" / "build_factor_panel_0913.py")
run(BASE / "backtest" / "oss_0913" / "build_oss_panel_0913.py")

# 验证
import pickle
import pandas as pd
idx = pd.read_csv(BASE / "index_000300.csv", parse_dates=["date"])
expect_last = idx["date"].dt.strftime("%Y-%m-%d").max()
with open(OSSP, "rb") as fh:
    P = pickle.load(fh)
cal = [str(d)[:10] for d in P["cal"]]
log(f"[验证] oss 面板 ND={len(cal)} | 末日={cal[-1]}（index 末日 {expect_last}）")
assert cal[-1] == expect_last, "面板末日与日历不一致"
E = P["ext"]
import numpy as np
cov = {k: round(float(np.isfinite(v).mean()), 3) for k, v in list(E.items())[:6]}
log(f"[验证] ext 因子覆盖（前6）: {cov}")
log("[完成] 面板已刷新")
