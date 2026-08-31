# 量化权重系统 · 目录结构说明（STRUCTURE.md）

> 本文件说明仓库/目录的完整结构、每个文件与数据目录的用途、以及数据格式。**新环境（公司电脑）落地时先读本文件**。

## 一、顶层目录树

```
quant-weight-system/
├── README.md                    # 快速开始 + 周一部署 Checklist（先读这个）
├── STRUCTURE.md                 # 本文件：目录结构说明
│
├── ★ 核心引擎（v8 体系，生产用）
│   ├── v8_selector.py           # 核心：因子计算 + 四因子打分 + 回测 + 全量池缓存
│   ├── v8_lite.py               # 个人版：自选池内轮动 Top4（★实际执行引擎）
│   ├── v8_lite_advice.py        # 生成加减仓建议页 advice_v8lite.html
│   ├── v8_triple_dashboard.py   # 生成四 tab 看板 index.html
│   ├── v8_mixed.py              # 混合引擎：全量池 Top15 主仓 + 固定池卫星
│   ├── v8_enhance3.py           # 增强引擎（卫星豁免波动 / 动态卫星 / 联动阈值）
│   ├── v8_fund_v5.py            # 基金动量选基（全市场净值池 + MA100 择时 + T+1）
│   ├── v8_etf_run.py            # ETF 独立回测
│   ├── v8_winrate.py            # 胜率优化引擎（移动止损/止盈参数化）
│   ├── v8_sprint2.py            # 参数化冲刺引擎（run_v8x）
│   ├── v8_attribution.py        # 分年度归因 + 空仓期现金管理测算
│   ├── v8_oos.py                # 样本外验证
│   ├── v8_daily_update.py       # 一键更新流水线（数据→缓存→回测→建议→看板）
│   └── v8_update.bat            # Windows 计划任务入口（schtasks 调用）
│
├── ★ 数据（运行时生成，见第二节）
│   ├── data_full/               # A股全量日线（7420 只，662MB）
│   ├── data_hist/               # 历史补充/场外基金（62 个，7.4MB）
│   ├── fund_nav_cache/          # 全市场基金净值（19359 只，593MB）
│   ├── index_000300.csv         # 沪深300 日线（择时门禁用）
│   ├── v8_factor_cache.pkl      # 全量池因子缓存（1.2GB，可重新生成）
│   ├── data_full_names.json     # 代码→名称映射（看板显示）
│   └── data_full_fail_list.csv  # 抓取失败清单（补数据用）
│
├── ★ 输出物（脚本生成）
│   ├── index.html               # 四 tab 看板（个人版/股票/ETF/基金）
│   ├── advice_v8lite.html       # 当月加减仓建议页（模板样式）
│   ├── v8_lite_equity.csv       # 个人版净值曲线（三件套）
│   ├── v8_lite_trades.csv       # 个人版交易记录
│   ├── v8_lite_summary.json     # 个人版绩效摘要
│   ├── v8_final_equity/trades/summary.*   # 股票主体系三件套
│   ├── v8_etf_equity/trades/summary.*     # ETF 体系三件套
│   └── v8_fund_equity/trades/summary.*    # 基金体系三件套
│
├── ★ 工具脚本
│   ├── compile_full_summary.py  # 拉全量 A 股日线到 data_full/（首次 1-2 小时）
│   ├── compile_hist_summary.py  # 历史数据补充
│   ├── fetch_full_universe.py   # 全市场标的清单拉取
│   ├── fetch_hist_akshare.py    # akshare 历史数据抓取
│   ├── build_subsample.py       # 1000 只分层子样本（实验用）
│   └── test_akshare.py          # 数据源连通性测试
│
├── backtest/  data/  docs/  legacy/  monitor/   # v4-v6 旧版（legacy 保留参考）
└── *.png                       # 检查截图（可随时删除）
```

## 二、数据格式说明（公司行情源对接标准）

### data_full/ 股票日线 CSV（`sh600000.csv` 示例）
```
date,open,high,low,close,volume,amount
2016-01-04,8.6,8.6,8.26,8.38,42240610.0,754425783.0
```
- 命名：`sh`/`sz`/`bj` + 6 位代码（`sh600000.csv`、`sz000001.csv`、`bj920000.csv`）
- 字段：date(YYYY-MM-DD) / open / high / low / close / volume(股) / amount(元)
- **对接公司行情源**：导出同列名 CSV 即可，无格式转换需求

### index_000300.csv（沪深300 日线）
```
date,open,high,low,close,volume
2015-01-05,3566.089,3669.042,3551.51,3641.541,45119811200
```
- 无 amount 列（引擎只用 close 算 MA200 择时）

### fund_nav_cache/ 基金净值 CSV（`008254.csv` 示例）
```
净值日期,单位净值
2024-01-02,1.5321
```
- 命名：6 位基金代码；字段：净值日期 / 单位净值
- 引擎内部转为 datetime index 的 Series

### 数据更新规则
- 股票/ETF：`compile_full_summary.py` 增量更新到最新交易日
- 基金：`v8_fund_system.py` 拉净值（akshare `fund_open_fund_info_em`）
- 缓存：`v8_factor_cache.pkl` 在数据更新后需重建（`load_pool(use_cache=False)` 或删掉 pkl 自动重建，约 1 分钟）

## 三、公司落地路径建议

```
公司机器建议结构（与仓库一致）：
D:\quant-weight-system\          # git clone 或 U 盘拷贝
├── data_full\                   # 从家里 U 盘拷入（662MB，必带）
├── fund_nav_cache\              # 从家里 U 盘拷入（593MB，必带）
├── index_000300.csv             # 从家里 U 盘拷入（164KB，必带）
└── （代码从 GitHub clone/pull）
```

**必带数据**：data_full/ + fund_nav_cache/ + data_hist/ + index_000300.csv + data_full_names.json（约 1.3GB）
**可选**：v8_factor_cache.pkl（1.2GB，公司重算仅 1 分钟）

## 四、验证命令（数据完整性自检）

```bash
python -c "
import v8_lite as L
pool = L.build_pool()          # 应打印 25 只自选池可用
eq, tr = L.run_lite(pool, top_n=4, hold_days=21, cash0=500000)
print(L.V.summary(eq, tr))     # 应输出 3923.68% / 1.644（与家里一致=数据完整）
"
```

> ⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。
