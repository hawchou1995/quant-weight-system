# 量化权重系统 v8（Quant Weight System v8）

A 股个人研究工具：**因子打分 + 截面选股 + 月度轮动 + 移动止损 + 大盘择时**，覆盖 **股票 / ETF / 基金** 三体系 + **个人版（v8-lite）**。纯 Python + pandas + akshare，无框架依赖。

> ⚠️ 个人研究工具，不构成任何投资建议。投资有风险，决策需谨慎。

## 版本历程

| 版本 | 说明 |
|---|---|
| v4-v6 | 六类加权打分（趋势/动能/量能/超买超卖/风控/研报）+ 每日信号快照（`legacy/` 保留） |
| **v8（当前）** | 四因子截面选股（动量 35% / 趋势 25% / Aroon 20% / 量价 20%）+ 月轮动 + 移动止损 + MA200 择时，全量池回测 |

## 系统架构（四体系）

```
quant-weight-system/
├── v9_auto.py               # ★普适版：全市场自动筛池→Top3（无人工选池，夏普1.715）
├── v9_signal.py             # v9 探索版（绝对信号体系，验证"无选择=市场平均"）
├── v8_selector.py          # 核心引擎：因子计算 + 打分 + 回测（全量池 5307 只缓存）
├── v8_sprint2.py            # 参数化冲刺引擎（run_v8x）
├── v8_mixed.py              # 混合引擎：全量池 Top15 主仓 + 固定池卫星
├── v8_enhance3.py           # 增强引擎（卫星豁免波动 / 动态卫星 / 联动阈值）
├── v8_lite.py               # ★个人版：自选池内轮动 Top4 + 整手约束 + 动态等权
├── v8_fund_v5.py            # 基金动量选基（全市场净值池 + MA100 择时 + T+1）
├── v8_lite_advice.py        # 加减仓建议页生成（模板样式 HTML）
├── v8_triple_dashboard.py   # 四 tab 看板渲染（个人版/股票/ETF/基金）
├── v8_daily_update.py       # 一键更新流水线（数据→回测→看板）
├── v8_etf_run.py            # ETF 独立回测
└── v8_update.bat            # Windows 计划任务入口
```

**五体系定位**：

| 体系 | 范围 | 持仓 | 频率 | 定位 |
|---|---|---|---|---|
| **普适版 v9-auto** | 全市场 5307 只自动筛池 | Top3 | 月轮动 | **无人工选池**（夏普 1.715，止损4.5%/MA150/动态门槛/RSI<85） |
| 个人版 | 自选池 40 只（主板10/创业板10/科创板10+ETF4+基金6，权限分层） | Top4 | 月轮动 20 笔/年 | 自选池执行（50 万中性资金，参数化） |
| 股票主体系 | 全市场 5307 只 | Top15 + 卫星 | 季度 | 策略研究基准 |
| ETF | 全市场 888 只 | Top10 | 半年 | 低波动配置 |
| 基金 | 全市场 16171 只 | Top10 + 卫星 | 半年 | 场外配置 |

## 快速开始

```bash
# 1. 环境
pip install akshare pandas numpy

# 2. 数据（akshare 全量日线，约 7400 只，首次约 1-2 小时）
python compile_full_summary.py        # 或自行抓取到 data_full/ 目录
python build_subsample.py             # （可选）1000 只分层子样本

# 3. 回测（个人版，15 秒内出结果）
python -c "
import sys; sys.path.insert(0,'.')
import v8_lite as L
pool = L.build_pool()
eq, tr = L.run_lite(pool, top_n=4, hold_days=21, use_timing=True, stop_loss=0.10, cash0=500000)
print(L.V.summary(eq, tr))
"

# 4. 生成加减仓建议页（08-14 口径示例）
python v8_lite_advice.py              # → advice_v8lite.html

# 5. 渲染四 tab 看板
python v8_triple_dashboard.py         # → index.html（个人版默认激活）

# 6. 每日/每月更新
v8_update.bat                          # 或 schtasks 注册

# 7. 普适版（全自动，无人工选池）
python -c "
import v9_auto as A
eq, tr = A.run_auto(top_n=3, mom_min=0.25, score_min=65, stop_loss=0.045,
                    dynamic=True, rsi_max=85, ma_window=150)
print(A.V.summary(eq, tr))             # +839.6% / 夏普 1.715
"
```

## 核心规则（个人版 v8-lite）

- **选股**：自选池内四因子打分（动量 35% / MA200 趋势 25% / Aroon 20% / 量价 20%），每月（21 交易日）重排，Top4 持仓
- **加仓**：只在再平衡日执行，一次性补足目标仓位（总资金/TopN），**信号持续 ≠ 继续加仓**
- **减仓三闸门**：① 移动止损——持仓峰值回撤 ≥10% 次日卖出 ② 月度换仓——排名跌出 Top4 卖出 ③ 大盘择时——沪深300 < MA200 全部清仓
- **执行**：T 日收盘信号 → T+1 开盘执行；A 股 T+1；100 股整手；佣金万 2.5 + 印花税

## 周一部署 Checklist（公司落地）

1. `pip install akshare pandas numpy`
2. 数据：跑 `compile_full_summary.py` 拉全量日线到 `data_full/`（或从公司行情源批量导出同名 CSV：`sh600000.csv` 等，列 `date/open/close/high/low/volume/amount`）
3. 自选池：修改 `v8_lite.py` 中 `STOCKS / ETFS` 清单（回测 25 只默认）；监控表分层池见 `build_enhanced_data.py` 的 `MAIN_CODES/GEM_CODES/STAR_CODES/ETFS/FUNDS`（40 只）
4. 验证回测：`python -c "import v8_lite as L; pool=L.build_pool(); print(L.V.summary(*L.run_lite(pool, top_n=4, hold_days=21)))"`
5. 调度：`schtasks /create /tn v8_dashboard_update /sc monthly /d 1 /st 18:00 /tr "<路径>\v8_update.bat"`
6. 看板：浏览器打开 `index.html`（个人版默认），`advice_v8lite.html` 为当月加减仓建议

## 已知限制

- 回测口径：T 日收盘触发 → T+1 开盘成交（止损为当日 close 触发当日 open 成交的近似，影响 <1%）；场外基金为 T+1 净值成交
- 新浪源 ETF 无复权参数，除权跳变已手工前复权修正；部分 ETF 数据末日与其他标的不同（mark-to-market 已兜底）
- 回测窗口 2016-01 ~ 2026-08；数据每日更新后重跑
- 个人版数字含"2026 强势池回测过去"的回顾偏置，外推需谨慎
- 未建模涨跌停不可成交（影响 <0.2%）

## 历史遗留（legacy/）

v4-v6 六类加权打分引擎与每日信号快照保留在 `legacy/`，供参考不回退。

> ⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。
