# A5 打板生产口径 · GitHub 镜像（v1.3 · 2026-09-15）

⚠ **只读镜像**——生产运行文件在 `D:/Documents/Workbuddy/股票基金/打板系统A5实验_20260827/`（`paper_daban_a5.py` / `spec_A5_tp8t2.md` / `paper_state.json` / `reports/`）。
本目录为版本管理副本：每次生产口径变更后从上述目录复制同步（`cp <生产目录>/paper_daban_a5.py <生产目录>/spec_A5_tp8t2.md a5_prod/`）。

v1.3 要点：双池独立滤网（池A 超跌 ret20≤-7.31% / 池B 趋势 ADX14≥27.9，独立成池不做交集）+ TP 8% 不变 + 验证门新口径独立计数（基准=并集 56.1%/+1.19%/tp25.0%）。
证据：`backtest/PRE-REGISTRATION_20260914_daban_opt.md`（R-daban-opt-0915）。
