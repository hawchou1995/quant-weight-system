# 量化权重系统 · 公司复现指南（v5.11.4）

> 周一在公司电脑从零复现：克隆仓库 → 装依赖 → 抓行情数据 → 构建看板。
> 全部数据**不入库**（data_full / fund_nav_cache / data_hist 均为本地生成），按下面顺序执行即可。

## 0. 环境要求

- Python 3.9+（本机用 `C:/Users/XAUTHUB/.workbuddy/binaries/python/envs/default` 的 3.x 环境）
- 依赖：`pandas` `numpy` `akshare` `requests`（`pip install pandas numpy akshare requests`）
- 约 15 GB 磁盘空间（行情数据）

## 1. 克隆仓库

```bash
git clone https://github.com/hawchou1995/quant-weight-system.git
cd quant-weight-system
```

仓库含：全部策略引擎（short_engine / v9_auto / v8_lite / v8_selector）、
回测与固化脚本、看板构建脚本（build_dual_system / build_enhanced_data / build_short_pool）、
复盘引擎（review_daily / update_daily / refresh_daily）、
已固化的回测结果（summary/equity json+csv）、看板 HTML、复盘记录（review/）。

## 2. 抓取行情数据（一次性，约 30-60 分钟）

| 步骤 | 命令 | 内容 | 耗时 |
|---|---|---|---|
| 1) 股票+ETF 全量 K 线 | `python fetch_full_universe.py` | data_full/ 约 7500 只（2016 至今，新浪源） | ~10 分钟 |
| 2) 增量补最新交易日 | `python update_daily.py` | 补齐滞后文件到最新（失败=退市/停牌，正常） | ~5-40 分钟（首日少） |
| 3) 基金净值（普适版池） | `python refresh_daily.py --skip-fetch --fund` | fund_nav_cache/ 前 3000 只（东财源） | ~20 分钟 |
| 4) 个人版基金/ETF 历史 | `python fetch_hist_akshare.py` | data_hist/（个人版 20 股+5 ETF+6 基金） | ~5 分钟 |

> 依赖顺序：步骤 2 需要步骤 1 先跑；步骤 3、4 相互独立可并行。

## 3. 构建看板

```bash
python build_enhanced_data.py     # 生成 enhanced_data.js（80 只标的详情）
python build_short_pool.py        # 生成短线信号池（short_pool.js + short_signals.js）
python build_dual_system.py       # 生成 dual_system.html（主看板）
python build_log_pages.py         # 生成独立日志页（review_log.html / changelog.html）
```

打开 `dual_system.html` 即完整看板（总览 12 卡回测 / 三池监控 / 复盘日志 / 更新日志）。

## 4. 每日收盘后刷新（15:30 跑一次）

```bash
python refresh_daily.py            # 行情增量 → 短线信号 → 看板 → 快照 → 复盘 → 日志（2-3 分钟）
```

- 基金净值更新需加 `--fund`（默认跳过，较慢）
- 复盘会自动生成 `review/` 新日志 + 更新 `review/review_index.json`；缺陷检测发现设计缺陷 → 手动在 `changelog.md` 登记版本

## 5. 版本对应

| 版本 | 内容 |
|---|---|
| v5.11.4 | 日志去重修复（复盘按 file 替换 / changelog 同版本去重 / md 转义） |
| v5.11.3 | 日志按日期/版本折叠；复盘权限列中文板块名 |
| v5.11.2 | 三池全量复盘（v9/v8/短线）；update_daily.py 真增量更新 |
| v5.11.1 | 复盘闭环系统（review_daily + 日志页） |
| v5.10.x | 短线 v3 混合策略 + 短线页修复 |

## 常见问题

- **抓取报错/失败清单**：`data_full_fail_list.csv` 里的多为退市/长期停牌股，不影响使用；ETF 数据滞后一天属新浪源特性，`update_daily.py` 会在下次运行时补齐
- **akshare 版本差异**：接口变动导致抓取失败时，先 `pip install -U akshare` 再重试
- **缺数据跑复盘报错**：确认 `data_full/`、`fund_nav_cache/`、`data_hist/` 三个目录已生成后再跑 build/refresh 链
