# -*- coding: utf-8 -*-
"""决定性对拍：冻结引擎 vs 我的引擎（同 comp、同数组、同参数）"""
import numpy as np, pandas as pd, time, sys
BASE_DIR = r"D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest/oss_0913"
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

src = open(BASE_DIR + "/oss_super_combo_0913.py", encoding="utf-8").read()
exec(src.split("comp = composite()")[0])
frozen_engine = run_engine
comp = composite()
log("冻结定义就绪")

sys.path.insert(0, BASE_DIR)
import oss_super_prod_0913 as S
COMP = S.COMP_SUPER                    # 我引擎的全局依赖
ELIG = S.ELIG_SUPER
MA20_BRK = np.zeros((S.ND, S.NC), dtype=bool)
AMP2X = np.zeros((S.ND, S.NC), dtype=bool)
SPCT = np.zeros((S.ND, S.NC)); IN2N = np.zeros((S.ND, S.NC), dtype=bool)
N, F = 20, 20
mine_all = open(BASE_DIR + "/exit_lab_trackB_0915.py", encoding="utf-8").read().splitlines()
i0 = next(i for i, l in enumerate(mine_all) if l.startswith("def run_exit"))
i1 = next(i for i, l in enumerate(mine_all) if l.startswith("res = {}"))
exec("\n".join(mine_all[i0:i1]).replace("def run_exit(", "def my_engine("))
log("我的引擎就绪")

mF = frozen_engine(comp, 20, offset=0)
mM = my_engine(exit_mode=None, offset=0)
log(f"冻结 off0: ann {mF['ann']*100:+.2f}% S={mF['sharpe']:.3f} mdd {mF['mdd']*100:.1f}% n={mF['n_trades']}")
log(f"我的 off0: ann {mM['ann']*100:+.2f}% S={mM['sharpe']:.3f} mdd {mM['mdd']*100:.1f}% n={mM['n_trades']}")
shF = [frozen_engine(comp, 20, offset=o)["sharpe"] for o in range(20)]
shM = [my_engine(exit_mode=None, offset=o)["sharpe"] for o in range(20)]
log(f"phmed: 冻结 {np.median(shF):.3f} | 我的 {np.median(shM):.3f}")
log(f"逐相位冻结: {[round(x,3) for x in shF]}")
log(f"逐相位我的: {[round(x,3) for x in shM]}")
