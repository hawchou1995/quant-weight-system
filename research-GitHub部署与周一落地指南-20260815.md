# 量化权重系统 GitHub 部署与周一公司落地指南 — 2026-08-15

> 触发：用户要求"系统更新到 GitHub + 编译知识库，周一去公司实现"。

## 一、GitHub 交付状态（2026-08-15 17:35）

- **仓库**：https://github.com/hawchou1995/quant-weight-system （**public**）
- **最新提交**：`2345a8b9`（v8 四体系 + 动态等权修复 + 脱敏清理）
- **已推送**：v8 全套引擎（`v8_selector/v8_lite/v8_mixed/v8_enhance3/v8_fund_v5/v8_lite_advice/v8_triple_dashboard` + 生产化脚本 + README）
- **已排除**：投研笔记（research-*.md）、持仓标注、中间实验结果、大数据（data_full/fund_nav_cache/pkl）——public 仓库安全清理完成，远程 0 残留
- **README**：含快速开始 + 核心规则 + 周一部署 Checklist

**⚠️ 已知残留**：git 历史 commit 仍含早期版本的部分投研文件（无凭据/密钥，风险为持仓信息可见）。如需彻底清除需 history rewrite（filter-repo + force push），会改变全部 SHA——如在意，周一前可执行。

## 二、周一公司落地 Checklist（README 同步版）

1. **环境**：`pip install akshare pandas numpy`（Python ≥3.9）
2. **数据**：
   - 首选：`python compile_full_summary.py` 拉全量日线到 `data_full/`（约 7400 只，1-2 小时）
   - 或公司行情源批量导出同名 CSV：`sh600000.csv` / `sz000001.csv`，列 `date/open/close/high/low/volume/amount`
   - 指数文件 `index_000300.csv`（沪深300 日线，择时用）
3. **自选池**：修改 `v8_lite.py` 中 `STOCKS / ETFS` 清单（默认 25 只 = 20 股 + 5 ETF）
4. **验证**：
   ```bash
   python -c "import v8_lite as L; pool=L.build_pool(); print(L.V.summary(*L.run_lite(pool, top_n=4, hold_days=21)))"
   ```
5. **加减仓建议**：`python v8_lite_advice.py` → `advice_v8lite.html`（模板样式：KPI + 净值 + 24 只档位表）
6. **看板**：`python v8_triple_dashboard.py` → `index.html`（四 tab：个人版默认）
7. **调度**：`schtasks /create /tn v8_dashboard_update /sc monthly /d 1 /st 18:00 /tr "<路径>\v8_update.bat"`
8. **更新流程**：`v8_daily_update.py`（数据→因子缓存→回测→建议→看板 一键流水线）

## 三、系统关键参数速查（公司实现时对照）

| 参数 | 值 | 位置 |
|---|---|---|
| 打分权重 | 动量 35% / 趋势 25% / Aroon 20% / 量价 20% | `v8_selector.score_row` |
| 持仓 | Top4（自选池内月轮动） | `v8_lite.py` |
| 轮动周期 | 21 交易日 | `hold_days=21` |
| 移动止损 | 峰值回撤 10% | `stop_loss=0.10` |
| 择时 | 沪深300 > MA200 | `v8_selector.load_index` |
| 资金 | 50 万中性（参数化 15/50/100 万） | `cash0` |
| 目标仓位 | 动态等权（当前市值/TopN） | `v8_lite.run_lite` |

**减仓三闸门**：① 移动止损 ② 月度换仓（排名跌出 Top4）③ 大盘择时清仓。
**加仓纪律**：只在再平衡日一次性补足目标仓位，信号持续 ≠ 继续加仓。

## 四、知识库内对应文档

- `research-v8-lite个人投资者版-20260815.md`（个人版全历程 + bug 修复）
- `research-量化权重v8中长线看板达标回测-20260815.md`（主体系）
- `research-量化权重v8三体系扩展-20260815.md` / `research-量化权重v8夏普冲刺最终版-20260815.md`
- `research-固定池诊断与增强矩阵-20260815.md` / `research-混合方案投产-20260815.md`

> ⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。
