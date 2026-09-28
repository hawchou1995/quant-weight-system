# 第三方跨引擎复核报告：backtrader × 「横盘低开·两日」组合记账层（2026-09-28）

- 复核对象：`backtest/hengpan_fangliang_dikai_0925/` 的**组合记账层**（勘误 E-15 所在的那一层）
- 复核引擎：**backtrader 1.9.78.123**（第三方事件驱动回测框架，经 `npx skills` 安装的技能）
- 复核脚本：`backtest/hengpan_fangliang_dikai_0925/bt_crosscheck.py`（**不 import** 本项目任何自研记账实现）
- 比对工装：会话 scratch 内 `bt_diff_authority.py`（引用权威 `x2_sens.sim_portfolio` 与一份**已证逐位等价**的净值转录）
- 结论：**复核通过**（四个口径臂全部满足判据；且**独立复现了 E-15 缺陷序与正确序两套读数**）

---

## 1. 技能来源与版本（A2）

| 项 | 值 |
|---|---|
| 仓库 | `https://github.com/lzwme/finance-quant-skills`（409★，A股量化 Agent Skills 合集） |
| **安装时 commit SHA** | **`d973f3595fc7e26ca00de347f76425ae289291ad`**（`git ls-remote … HEAD` / `refs/heads/main`） |
| 安装器 | `npx skills`（**v1.7.0**），命令 `npx skills add lzwme/finance-quant-skills -g -a cline -y --copy` |
| 落地根 | `~/.agents/skills`（= 安装器 `cline` 条目的 `globalSkillsDir`；即 PI-Desktop 读取的技能根） |
| 安装结果 | **14 / 14 成功**（13 个技能 + `template-skill`） |
| 本次实际使用的技能 | **`backtrader`**（另下载 13 个备用，其中需券商客户端/账号者标注「已安装未运行验证」） |

`npx skills ls -g --json` 中本仓 14 个条目的 `source` 均为 `lzwme/finance-quant-skills` —— **归属核验 14/14 正确**。

**安装清单（技能 / 文件数）**：akshare 16、baostock 37、jqdatasdk 8、miniqmt 14、pywencai 1、tdxquant 15、tushare 7、akquant 7、backtrader 2、equity-researcher 35、joinquant-strategy 20、qmt-strategy 36、rqalpha 2、template-skill 1。

**已安装未运行验证（如实登记）**：`miniqmt` / `qmt-strategy`（需 QMT 客户端）、`jqdatasdk`（需聚宽账号）、`tushare`（需 token）、`pywencai`（需 Cookie）、`rqalpha` / `akquant`（依赖未安装）。这些技能**只完成安装与静态审查**，**未做运行验证**。

---

## 2. 安装期覆盖与影响（A3，如实披露）

安装器**未跳过同名技能**，直接**覆盖**了本机既有技能：

| 技能 | 安装前 | 安装后 | 新增 | 删除 | 修改 |
|---|---|---|---|---|---|
| `baostock` | 9 文件 | 37 文件 | 36 | 8 | 1（`SKILL.md`） |
| `tushare` | 4 文件 | 7 文件 | 6 | 3 | 1（`SKILL.md`） |

**删除的旧文件**（baostock）：`QUICK_REFERENCE.md`、`README.md`、`_meta.json`、`demo_project/README.md`、`demo_project/demo.py`、`metadata.json`、`requirements.txt`、`skill-card.md`；
（tushare）：`references/数据接口.md`、`scripts/fund_data_demo.py`、`scripts/stock_data_demo.py`。

**处置**：安装前已把这两个技能的**完整快照**备份到会话 scratch
（`$env:PI_SCRATCH_DIR/fqs_baseline/skill_baostock`、`…/skill_tushare`，含逐文件 SHA256 清单）。
本次**未回滚**（用户选择「全部安装」，且新版内容更完整）；**如需恢复旧版 demo/QUICK_REFERENCE，可自该备份取回**。

---

## 3. 第三方技能安全审查（A4，只审查不改动）

对 14 个技能的 `SKILL.md` 与其引用的脚本/文档（共 **205 个文本文件**）做模式扫描（远程下载并执行 / 凭据读取 / 外传本地文件 / 写系统配置 / 递归删除 / 动态执行 / 子进程 / 装依赖 / 持久化 / 遥测上报）。

| 技能 | 文本件 | 命中 | 级别 | 结论 |
|---|---|---|---|---|
| akshare | 16 | 3 | LOW/MED | 未检出风险行为（命中的是文档里的 URL 与「股票代码」字样） |
| baostock | 37 | 2 | LOW | 未检出 |
| jqdatasdk | 8 | 10 | LOW/MED | 命中的是**正常的账号/Token 配置说明** |
| miniqmt | 14 | 4 | LOW/MED | 正常的 xtquant 下载与配置说明 |
| pywencai | 1 | 1 | LOW | 正常的 Cookie 说明 |
| tdxquant | 15 | 1 | LOW | 未检出 |
| tushare | 7 | 12 | LOW/MED | 正常的 **token 使用说明** |
| **akquant** | 7 | 1 | **HIGH** | ⚠ 唯一 HIGH：文档中的 **`uv` 官方安装命令**（`curl -LsSf https://astral.sh/uv/install.sh \| sh`）—— 属**前置依赖的官方安装指引**，非隐蔽外联；**本次未执行** |
| backtrader | 2 | 1 | LOW | 未检出（本次实际使用的技能） |
| equity-researcher | 33 | 14 | LOW/MED | 命中的是**产出报告里的路径模板**，非写系统文件 |
| joinquant-strategy | 20 | 4 | LOW/MED | 正常文档 |
| qmt-strategy | 36 | 4 | LOW/MED | 正常文档（安装器的第三方扫描亦报 4 alerts） |
| rqalpha | 2 | 1 | LOW | 未检出 |
| template-skill | 1 | 0 | — | 空模板 |

**判定**：**未检出任一技能存在「外传本地数据 / 下载并执行远程代码（除上述官方依赖安装指引）/ 覆盖系统文件 / 静默修改配置」的行为**。
按契约，本次**未修改**第三方技能的任何文件。

---

## 4. 口径映射表（自研 → backtrader，逐条披露）

| # | 口径项 | 自研（权威） | 本次 backtrader 实现 | 说明 |
|---|---|---|---|---|
| 1 | 账户记账 | 自写标量 `cash` + `nav` 数组 | **backtrader Broker** | 订单生命周期、现金、持仓、佣金、盯市全部交给引擎 |
| 2 | 每日选股顺序 | `by_entry[日][:K]`（复合分降序） | 同（按同一份冻结逐笔的原始顺序遍历） | 完全一致 |
| 3 | 入场时点/价 | 当日**开盘**价 `entry_open` | `cheat_on_open=True` + `next_open()` 下限价/市价单 → **当根开盘成交** | 逐笔核验成交价 = `entry_open` |
| 4 | 出场时点/价 | 当日 **`exit_px`**（止盈价或 T+2 收盘） | `bt.Order.Close` → **次一根收盘成交**，该根 `close` 线置为 `exit_px` | 逐笔核验成交价 = `exit_px`（8 例抽验全等） |
| 5 | 成本 | `alloc/(px(1+c))` 股数、卖出 `×(1−c)` | `CommInfoBase(COMM_PERC, stocklike, percabs=True, commission=c)` | 引擎实扣 = `size×price×(1±c)`，**与自研逐位同式**（微测验证） |
| 6 | 额度规则 | `alloc = min(前一日净值/KSLOT, 可用现金)` | **同式**，由本脚本施加（见 #7） | 含 `alloc ≤ 1e-12 → break` 分支，**逐位复现** |
| 7 | 资金可用性（**E-15 本体**） | `entry_first`：只用**结算前**现金；`exit_first`：当天回笼先可用 | 由 `_open_step` 的现金镜像决定；两种变体**仅此一处不同** | 见 §6 的方向确认 |
| 8 | 现金校验 | 自研为纯标量比较 | **关闭 backtrader 的「提交期伪执行校验」** `set_checksubmit(False)` | 该内建校验会把同批次卖单回笼先记入可用现金（即缺陷序语义），与本次要复核的额度规则不同族；真实执行期校验仍由 broker 执行 |
| 9 | 下单规模 | `alloc/(px(1+c))` | **二分求「引擎自身费用函数允许的最大规模」**，上限 `min(实际现金, 额度×(1−1e-6))` | 见 §7 差异定位；`1e-6` 安全系数用于吸收面板 float32 盯市带来的 ~1e-7 现金噪声 |
| 10 | 逐日盯市 | 面板收盘 `C[t,j]`，缺失则回落到 `entry_px` | **同**（取面板收盘，非数据馈 close 线） | 799 笔「同日既出又入」的标的上，`close` 线被出场价占用，故盯市必须直接取面板 |
| 11 | 净值起点归一 | `nav[i0] = 1.0` | 同（v[0] = 1.0） | 一致 |
| 12 | 指标公式 | `ann=(v[-1]/v[0])^(244/nd)−1`；`sd=dr.std(ddof=1)`；`sharpe=mean/sd×√244`；`mdd=min(v/maxacc−1)` | **同式**（由脚本按同一公式计算，便于逐项对拍） | 另用 `SharpeRatio`/`DrawDown` 分析器作旁证 |

**backtrader 提供的原生能力（本次真实使用）**：`Cerebro`（引擎与事件循环）、`Strategy`（策略钩子 `next_open`/`next`/`notify_order`/`stop`）、`feeds.PandasData`（每标的 1 个数据馈，共 **2,390 个**）、`Broker`（订单撮合、现金、持仓、`getoperationcost`/`getcommission`）、`CommInfoBase`、`Analyzer`（`SharpeRatio` / `DrawDown` / `TimeReturn`）。
**引擎原生结论 vs 本次自定口径**：记账与成交全部来自引擎；**自定**的仅 #6/#7/#9 三处额度与规模决策（已列明），以及 #10 的盯市取数。

---

## 5. 规模与运行

- 输入：冻结逐笔 **23,759 笔**（主板 `_v_g00_trades.jsonl`）+ 面板 **2,852 日 × 5,442 只**（`panel_oos.npz`）
- 数据馈：**2,390 个标的 × 2,852 日 = 681.6 万 bar**（`runonce=False` 逐 bar 执行）
- 单臂耗时 **557 ~ 646 秒**（约 10 分钟），四臂共约 40 分钟

---

## 6. 对拍结果（A6）与 E-15 方向独立确认（A7）

### 6.1 正确序 `entry_first` —— 与自研权威口径对拍

| KSLOT | 指标 | 自研权威 | backtrader | **Δ** | 判据 | 结果 |
|---|---|---|---|---|---|---|
| **20** | 年化 | +47.17% | **+47.1729%** | **+0.0029pp** | ≤0.10pp | ✅ |
| 20 | 最大回撤 | −26.81% | **−26.8084%** | +0.0016pp | ≤0.10pp | ✅ |
| 20 | 夏普 | 2.19 | **2.1937** | +0.0037 | ≤0.05 | ✅ |
| 20 | 入场笔数 | 23,002 | **23,002** | **0** | 必须相同 | ✅ |
| 20 | 资金占用 | 40.43% | **40.4349%** | +0.0049pp | — | — |
| 20 | **逐日净值最大相对偏差** | — | — | **3.661e-06** | ≤1e-04 | ✅ |
| **4** | 年化 | +76.61% | **+76.6112%** | **+0.0012pp** | ≤0.10pp | ✅ |
| 4 | 最大回撤 | −33.63% | **−33.6323%** | −0.0023pp | ≤0.10pp | ✅ |
| 4 | 夏普 | 2.29 | **2.2919** | +0.0019 | ≤0.05 | ✅ |
| 4 | 入场笔数 | 4,886 | **4,886** | **0** | 必须相同 | ✅ |
| 4 | 资金占用 | 42.82% | **42.8247%** | +0.0047pp | — | — |
| 4 | **逐日净值最大相对偏差** | — | — | **3.107e-06** | ≤1e-04 | ✅ |

**运行健壮性（四臂全为 0）**：保证金拒单 0、订单拒绝 0、期末未平仓 0、**现金一致性审计违规 0**（逐 bar 比对「引擎真实现金 vs 本脚本现金镜像」，最大偏差 < 1e-9）。

### 6.2 缺陷序 `exit_first` —— 独立复现 E-15 之前的旧读数

第三方引擎**在只改变「资金可用性规则」一处的前提下**，复现了勘误 E-15 记录的全部旧读数：

| 臂 | 缺陷序 exit_first（第三方引擎） | 旧读数（E-15 前） | Δ | 正确序 entry_first（第三方引擎） | 现行权威 | Δ |
|---|---|---|---|---|---|---|
| KSLOT=20 | **+47.7716%** / MDD **−29.1325%** | +47.77% / −29.13% | +0.0016pp / −0.0025pp | **+47.1729%** | +47.17% | +0.0029pp |
| KSLOT=4 | **+189.7509%** / MDD **−51.1802%** | +189.75% / −51.18% | +0.0009pp / −0.0002pp | **+76.6112%** | +76.61% | +0.0012pp |
| 入场笔数 | 23,759 / 9,620 | 23,759 / 9,620 | **0** | 23,002 / 4,886 | 23,002 / 4,886 | **0** |
| 逐日最大相对偏差 | 4.357e-06 / 1.150e-05 | — | ≤1e-04 ✅ | 3.661e-06 / 3.107e-06 | — | ≤1e-04 ✅ |

**这就是 E-15 的决定性独立证据**：两套读数由**同一份输入、同一套引擎、同一份代码**产生，**唯一变量是「当天回笼的资金能否用于当天开盘的买入」**。
- 允许复用（缺陷序）→ **+47.77% / +189.75%**（与旧读数一致）；
- 禁止复用（正确序）→ **+47.17% / +76.61%**（与现行权威一致）。

第三方引擎独立确认了 E-15 的**方向与量级**：低 KSLOT 高占用档被高估 **113.14pp**（KSLOT=4 全窗），KSLOT=20 仅 −0.60pp。

---

## 7. 对拍过程中定位并修正的 4 处实现差异（如实留档）

跨引擎对拍不是「一遍就过」。以下 4 处差异均为**我方桥接实现**的问题（**权威读数与 `oos_run.py` 从未改动**），逐一定位并修正后才得到 §6 结果：

| # | 现象 | 定位 | 修正 |
|---|---|---|---|
| 1 | 入场清单差 3 笔 | 保证金拒单 3 笔（成本恰好等于可用现金的严格边界）→ 我方台账留下**幽灵持仓** → 次日 KSLOT 未满而多入 | 拒单即清理台账；下单规模改用**引擎自身费用函数二分**求最大可成交规模 |
| 2 | 买入按**出场价**成交 | 799 笔「**同日既出又入**」的标的上，我把出场价覆盖到了数据馈的 `open` 字段，买单一并受影响 | `open` 只承载入场价、`close` 只承载出场价；出场单统一用 `Order.Close` |
| 3 | 单日净值尖峰 2.2% | 同上 799 例中，**当日新买入的持仓**被按出场价盯市 | 盯市改为**直接取面板收盘序列**（与权威同源）+ 缺失回落 `entry_px` |
| 4 | 缺陷序 KSLOT=4 多入 1 笔（9,621 vs 9,620） | 权威在该处走 `alloc ≤ 1e-12 → break`（现金耗尽），我的 1e-6 安全系数留下 ~3.5e-7 余量 | **额度判据严格按权威规则（不含安全系数）**，安全系数只作用于下单规模 |

> 差异 1 与 4 属同一族：**浮点/边界语义**（与 E-15 本身的成因同族）。这也是本次复核最有价值的副产品 —— 它说明「额度恰好等于可用现金」这类边界在跨引擎复现中必须显式处理。

---

## 8. 结论

**复核通过。**

1. 第三方引擎 **backtrader 1.9.78.123** 在**不使用本项目的任何记账实现**、只读冻结逐笔与面板的前提下，独立复现了「横盘低开·两日」组合记账层的全部关键读数；
2. **四个口径臂（2 种日序 × 2 档 KSLOT）全部满足判据**：入场笔数**逐臂完全一致**，逐日净值最大相对偏差 **≤ 1.15e-05**（阈值 1e-04），年化 |Δ| **≤ 0.0029pp**（阈值 0.10pp），最大回撤 |Δ| **≤ 0.0025pp**，夏普 |Δ| **≤ 0.0046**（阈值 0.05）；
3. **E-15（T+0 资金时序）得到独立确认**：缺陷序与正确序由同一代码、同一输入、**唯一变量为资金可用性规则**产生两套读数，分别与旧读数、现行权威读数吻合（Δ ≤ 0.0025pp）；
4. 现金一致性审计**零违规**，无保证金拒单、无订单拒绝、无期末未平仓。

**因此，`x2_sens.sim_portfolio` 在 E-15 修正后的记账口径（主板 / KSLOT∈{20,4} / 全窗）获得了跨引擎的独立背书。**

---

## 9. 复现

```bat
:: 安装技能（含 backtrader）
npx skills add lzwme/finance-quant-skills -g -a cline -y --copy

:: 安装引擎（纯 Python，无依赖）
python -m pip install backtrader

:: 跨引擎对拍（四臂；每臂约 10 分钟）
python backtest/hengpan_fangliang_dikai_0925/bt_crosscheck.py --cache <缓存目录> ^
  --kslot 20 --order entry_first --out out_ef_k20.json
python backtest/hengpan_fangliang_dikai_0925/bt_crosscheck.py --cache <缓存目录> ^
  --kslot 4  --order entry_first --out out_ef_k4.json
python backtest/hengpan_fangliang_dikai_0925/bt_crosscheck.py --cache <缓存目录> ^
  --kslot 20 --order exit_first  --out out_xf_k20.json
python backtest/hengpan_fangliang_dikai_0925/bt_crosscheck.py --cache <缓存目录> ^
  --kslot 4  --order exit_first  --out out_xf_k4.json
```

脚本输出的 `*.nav.npy` / `*.dates.txt` 为逐日净值序列；与自研权威的逐日比对由会话 scratch 的
`bt_diff_authority.py` 完成（先验证净值转录与 `sim_portfolio` 指标在权威显示精度上**逐位等价**，再逐日比对）。

---

## 10. 局限与本报告**不能**证明什么

1. **复核范围仅限记账层**。信号层（选股与排序）由既有 A11 25/25 逐位对拍与四闸覆盖；数据层（双源交叉、复权、日历）由既有数据核验覆盖。本报告不重复、也不替代它们。
2. **四处自定口径**（§4 的 #6/#7/#9/#10）由我方施加，非引擎内建。其中 `set_checksubmit(False)` 关闭了 backtrader 的提交期现金校验 —— 若不做该处理，引擎会用「缺陷序」的语义（同批次卖单回笼先可用）判保证金，与本次要复核的规则不同族。**引擎仍完成真实执行期校验**，且实测四臂保证金拒单为 0。
3. **1e-6 安全系数**使下单规模系统性小 1e-6 相对量级（用于吸收面板 float32 盯市带来的 ~1e-7 现金噪声）。它带来的偏差已包含在 §6 的 Δ 里（≤0.005pp），但它**不是零**。
4. **面板 float32 精度**：输入本身为 float32，双方净值因此带有 ~1e-6 量级噪声（§6 的逐日偏差即此量级）。这意味着**无法**用本方法分辨 1e-6 以下的记账差异。
5. **不能证明策略有效**。本报告只证明「自研记账实现可被另一引擎复现」，与「策略未来能否盈利」无关；前瞻判断仍以前向 OOS（首个信号日 2026-09-28）为准。
6. **只验证了两种日序**（`entry_first` / `exit_first`）。其它可能的时序变体（如盘中分批、T+1 出场）未验证。
7. **第三方技能安全性**：§3 为**模式扫描 + 人工判读**，不是形式化审计；`miniqmt` / `qmt-strategy` / `jqdatasdk` / `tushare` / `pywencai` / `rqalpha` / `akquant` **未做运行验证**。
8. **安装覆盖**（§2）：`baostock` 与 `tushare` 的旧版文件已被新版替换（备份在会话 scratch，**回滚需人工操作**）。

---

## 附：本次交付的文件

| 文件 | 说明 |
|---|---|
| `backtest/hengpan_fangliang_dikai_0925/bt_crosscheck.py` | 第三方跨引擎复核脚本（新增；不 import 自研实现） |
| `backtest/报告-第三方复核-backtrader跨引擎对拍-20260928.md` | 本报告（新增） |
| 会话 scratch | `fqs_baseline/`（安装前基线、旧技能快照、安装核验、安全审查）、`bt_diff_authority.py`（比对工装）、四臂 JSON/nav 序列 |

**零改动清单**：`oos_run.py`、`x2_sens.py`、`x5_gates.py`、`x3_board.py`、`x6_t0_audit.py`、`gen_gates_report.py`、
`evidence_*.json`、`hpdk_bt_ref.json`、`hpdk_candidates.json`、`hpdk_oos_view.json`、预注册文件、`dual_system.html`、`index.html`
（安装前后 SHA256 逐文件比对，见 §A10 核验）。
