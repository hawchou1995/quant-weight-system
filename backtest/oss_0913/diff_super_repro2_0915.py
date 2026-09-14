# -*- coding: utf-8 -*-
"""定位差异第2步：冻结脚本的引擎输入数组 vs prod 模块的数组（逐一对拍）"""
import numpy as np, pandas as pd, time, sys
BASE_DIR = r"D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest/oss_0913"
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

src = open(BASE_DIR + "/oss_super_combo_0913.py", encoding="utf-8").read()
exec(src.split("comp = composite()")[0])
log("冻结定义载入")
sys.path.insert(0, BASE_DIR)
import oss_super_prod_0913 as S
log("prod 载入")

pairs = [("WARMUP", WARMUP, S.WARMUP), ("F", F, 20), ("ND", ND, S.ND), ("NC", NC, S.NC),
         ("cal 长度", len(cal), len(S.cal)), ("cal 末日期", cal[-1], S.cal[-1]),
         ("O", O, S.O), ("C", C, S.C), ("close_ff", close_ff, S.close_ff),
         ("ELIG(bool)", ELIG3, S.ELIG_SUPER)]
for name, a, b in pairs:
    if isinstance(a, (int, float, str)) or a is None:
        same = (a == b)
        log(f"{name}: 冻结={a} | prod={b} | {'一致' if same else '★不一致'}")
        continue
    if hasattr(a, 'shape') and getattr(a, 'dtype', None) == bool:
        diff = int((a != b).sum())
        log(f"{name}: 形状 {a.shape} | bool 不一致元素 {diff} | {'一致' if diff == 0 else '★不一致'}")
        continue
    m = np.isfinite(a) & np.isfinite(b)
    fin_diff = int((np.isfinite(a) != np.isfinite(b)).sum())
    d = float(np.nanmax(np.abs(a[m] - b[m]))) if m.sum() else float('nan')
    log(f"{name}: 形状 {a.shape} | 有限性差异 {fin_diff} | max|diff| {d:.6g} | {'一致' if (fin_diff == 0 and d <= 1e-9) else '★不一致'}")

# volpct 对拍（各自用各自的 close_ff/ELIG 重建）
r1 = pd.DataFrame(close_ff).pct_change(); v1 = (-r1.rolling(20, min_periods=15).std()).to_numpy()
volpct_f = pd.DataFrame(np.where(ELIG3, v1, np.nan)).rank(axis=1, pct=True).to_numpy()
r2 = pd.DataFrame(S.close_ff).pct_change(); v2 = (-r2.rolling(20, min_periods=15).std()).to_numpy()
volpct_p = pd.DataFrame(np.where(S.ELIG_SUPER, v2, np.nan)).rank(axis=1, pct=True).to_numpy()
m = np.isfinite(volpct_f) & np.isfinite(volpct_p)
log(f"volpct: 有限性差异 {int((np.isfinite(volpct_f) != np.isfinite(volpct_p)).sum())} | max|diff| {float(np.nanmax(np.abs(volpct_f[m]-volpct_p[m]))):.6g}")

# 若数组全同：直接文本对比两个 run_engine
if True:
    lines = src.splitlines()
    # 冻结引擎源码（从 'def run_engine' 到 'comp = composite()' 之前）
    i0 = next(i for i, l in enumerate(lines) if l.startswith("def run_engine"))
    i1 = next(i for i, l in enumerate(lines) if l.startswith("comp = composite()"))
    frozen_src = "\n".join(lines[i0:i1])
    open("_frozen_engine_src.txt", "w", encoding="utf-8").write(frozen_src)
    log(f"冻结引擎源码已导出 _frozen_engine_src.txt（{i1-i0} 行）")
