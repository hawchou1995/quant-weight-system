# 量化权重系统（Quant Weight System）

A 股多指标加权打分系统：六类指标连续打分（趋势/动能/量能/超买超卖/风控/研报）→ 加权合成总分 0-100 → 映射加仓/观望/减仓操作。内置回测引擎、每日信号快照、HTML 仪表盘、39 只跨行业验证池、公司设备可移植部署。

## 快速开始

```bash
# 1. 环境：Python 3.10+，安装依赖
pip install pandas numpy matplotlib

# 2. 配置数据源（config.py 自动探测；也可用环境变量覆盖）
export WSTOCK_CLI=/path/to/westock-data/index.js   # 行情 CLI（可选）

# 3. 运行回测（19 标的等权组合，2025-01 起）
python weight_system_backtest.py

# 4. 每日信号快照（操作建议 + 变动记录 + 置信度 + 数据溯源）
python make_snapshot_v2.py

# 5. HTML 仪表盘
python render_dash_v2.py

# 6. 移植自检（17 项，公司设备部署后必跑）
python self_check.py
```

## 核心文件

| 文件 | 用途 |
|------|------|
| `weight_system_backtest.py` | 回测引擎（六类打分/置信度/数据溯源/v1.3 开关） |
| `config.py` | 统一配置（路径/数据源/取数预算/置信度规则）——移植唯一需改文件 |
| `make_snapshot_v2.py` | 每日快照（含操作建议+前后变动记录） |
| `render_dash_v2.py` | HTML 仪表盘渲染 |
| `validate_industry_v2.py` | 39 只 × 19 领域跨行业验证（权重调整试金石） |
| `fetch_stocks.py` / `fetch_tmp_balanced.py` | 行情取数（19 关注 + 39 验证） |
| `compare_v13.py` | v1.3 死区/反转才动开关对比 |
| `self_check.py` | 移植自检 17 项 |

## 配置开关（v1.3）

`weight_system_backtest.py` 顶部：

```python
USE_DEADBAND = False        # 55-65 分死区观望（防临界抖动，收益 -1.9pct）
USE_REVERSAL_ONLY = False   # 仅加减反转才动（实测 -68pct，证伪，勿开）
```

默认全关 = v1.2 基线（组合 +220.3% / 回撤 18.8% / 夏普 2.27）。

## 数据

- `data/`：19 只关注标的日线（qfq，westock）
- `data_tmp/`：39 只 × 19 领域验证标的日线
- 基金净值（`data/008254.csv` 等）为 T-1 口径（通达信 setcode=33）

## 公司设备部署

1. `git clone` 本仓库（或 git pull 更新）
2. 装 Python + `pip install pandas numpy matplotlib`
3. 改 `config.py` 或设环境变量接入公司数据源
4. `python self_check.py` → 17/17 PASS 即部署成功

详细手册见知识库 `research-量化权重系统部署手册-20260810.md`。

## 说明

> 本项目为个人量化研究工具，输出仅供参考，不构成投资建议。
