# -*- coding: utf-8 -*-
"""每日收盘后一键刷新（三轨体系·全量）：数据 → 池 → 复盘 → 信号 → 看板 → 部署 → 同步 main
用法：python daily_refresh.py [--skip-deploy] [--skip-data] [--force] [--no-main-push] [--skip-gushi]
非交易日自动跳过（index_000300.csv 最后日期 != 今天 时，除非 --force）。
"""
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
_A5_EXT = BASE.parent / "打板系统A5实验_20260827"   # 本机实验目录；云端不存在 → 回落仓库内 backtest/a5_experiment
PY = sys.executable
FORCE = "--force" in sys.argv
# ---- 云端复用开关（2026-09-24 新增；默认行为不变，仅显式传参时生效）----
NO_MAIN_PUSH = "--no-main-push" in sys.argv   # 云端不 push main（Phase 1：发布走 peaceiris → gh-pages）
SKIP_GUSHI = "--skip-gushi" in sys.argv       # 云端无本机 Chrome 自动化 profile → 跳过采集（故也不续费）

# ---- 交易日闸门（R-gate-0917 重构：数据步后置 + HS300 行自动维护）----
# 旧逻辑以「index_000300.csv 末行==今天」判交易日，但该文件仓库无写手（长期靠人工"补 HS300 指数行"，
# 见 09-16 提交说明）→ 15:30 自动链时末行必为昨天 → 恒输出 [skip] 非交易日 → 实际全靠傍晚人工
# --force 追跑（09-16 卡死进程的命令行带 --force 即证）。
# 新逻辑：① 周末直接跳过；② 工作日先跑数据步，再由链内步骤 ensure_index_row 判定——
#   今日 HS300 行情可取得 = 交易日 → 自动写入/刷新 index_000300.csv（消除人工补行 + 修正
#   review_daily 等步骤的 as-of 依赖）；不可取得（节假日/数据源未就绪）= 非交易日 →
#   该步 exit 3 → 主链打印 skip 并干净退出（数据步已完成，无副作用）。
if not FORCE and date.today().weekday() >= 5:
    _wd = "一二三四五六日"[date.today().weekday()]
    print(f"[skip] 周末（{date.today().strftime('%Y-%m-%d')} 周{_wd}）——收盘刷新无需执行", flush=True)
    sys.exit(0)

STEPS = [
    ("数据更新 update_daily", ["update_daily.py"], "--skip-data" in sys.argv),
    # HS300 指数行维护 + 交易日闸门（R-gate-0917）：exit 3 = 今日行情不可得（非交易日/未就绪）→ 主链跳过后续
    # 2026-09-21 修：**必须紧跟在数据更新之后**——它是唯一写入 index_000300 当日行的步骤，
    # 而 fullpool_guard / em_bulk 都靠该文件末行判定「今日」。原先排在它们之后
    # → 三步拿到上一交易日做基准：freshness 误报新鲜、guard 漏补、em_bulk 口径校验拒写(rc=2)。
    ("HS300 索引行 ensure_index_row", ["backtest/ensure_index_row.py"], False),
    # 全量池守卫（R-fullpool-0917，2026-09-17 建）：降级源只补池内子集（如 440/7539）→ 全市场口径
    # 数据（涨停全景/A5 扫描）失真。本步查 data_full 新鲜度，陈旧 >100 只自动触发全量补数（约 1-2h）。
    # [软]=失败不阻断主链；--skip-fullguard 跳过。
    ("全量池守卫 fullpool_guard[软]", ["backtest/fullpool_guard.py"], "--skip-fullguard" in sys.argv),
    # 东财全市场批量补齐（R-em-bulk-0918 · 用户 2026-09-18 批准）：A股(5560只/11s) → ETF/LOF(1751只/3s)
    # → 单只端点兜底。全部幂等（只补「本地末行 < 交易日」），正常日待补 0；三源同时滞后时是唯一
    # 能十几秒补齐全市场的通道。实测：A股 4191 只、ETF 704 只、残余 26 只一次补全。
    # [软]=失败不阻断主链；--skip-embulk 跳过。
    # 2026-09-23 起本机实测：东财 push2* 家族持久被拦（clist/stock/ulist 502 / 握手超时，出口无关、非指纹）
    # → 本步定位为「完整性兜底」且 [软]：被拦时每步 ≤3 次单发探测即退（秒级），不阻断当日数据；
    #   当日补齐主力已移到 update_daily.py 内的「批量通道」（腾讯快照 400 码/请求，全市场 ≈6s）。
    ("东财批量补齐 em_bulk[软]", ["backtest/em_bulk_all.py"], "--skip-embulk" in sys.argv),
    # 估值日更（2026-09-17 建，R-valfreeze-0917）：根因=旧管道只写 4 列快照、从不扩展 val_em 主表
    # → 主表冻结 → factorlab/oss 面板冻结 → 生产轨B 目标清单冻结（asof 谎报）。[软]=失败不阻断。
    ("估值日更 fetch_val_em_daily[软]", ["fetch_val_em_daily.py"], "--skip-val" in sys.argv),
    # 基金净值刷新：必须在 build_short_pool 之前——否则基金信号用旧净值排序
    # 2026-09-14 补：此前刷新逻辑只在 refresh_daily.py --fund，收盘链从不调用 → 92% 的基金净值停在 08-20，
    # 占 60% 仓位的 FB3 基金主仓长期用 3 周前净值选基（且新旧净值混算）。[软]=失败不阻断主链。
    ("基金净值刷新 fund_nav_update[软]", ["fund_nav_update.py"], "--skip-fundnav" in sys.argv),
    ("短池+门控+FB3基金池 build_short_pool", ["build_short_pool.py"], False),
    # 全量池因子缓存重建（R-v8cache-0921 · 2026-09-21 用户批准接进日链）：
    # 根因=v9_auto.py:14 `pool_all = V.load_pool()` 在 **import 时**就读 v8_factor_cache.pkl，
    # 而该缓存此前**从不被日链刷新**（源是 data_full，属派生缓存）→ 缓存一冻，
    # build_enhanced_data 的 meta.as_of 就冻 → **看板页面标题「数据截至 X」与中长线池的
    # 股价/评分一起停住**。实测事故：缓存停 09-15 → 线上标题写「数据截至 2026-09-18」，
    # 而全市场数据已到 09-21（用户报「看板还是旧的」）。
    # 必须排在 review_daily **之前**——review_daily.py:31 `import build_enhanced_data` 即执行。
    # 幂等：sidecar `v8_factor_cache.meta.json` 的 as_of ≥ 交易日 → 跳过（正常日 0 成本）；
    # 陈旧时全量重算（实测 5394 只 / 1.6 分钟 / 1.33 GB，原子替换，末行回退即拒写）。
    # [软]=失败不阻断主链（看板退回旧缓存渲染，但不会静默写坏缓存）；--skip-v8cache 跳过。
    ("全量池因子缓存 rebuild_v8cache[软]", ["backtest/rebuild_v8cache.py"], "--skip-v8cache" in sys.argv),
    ("复盘日志+跟踪池 review_daily", ["review_daily.py"], False),
    ("复盘日志页 build_log_pages", ["build_log_pages.py"], False),
    ("市值快照 fetch_val_daily", ["backtest/fetch_val_daily.py"], False),
    # 面板刷新 + 影子轨（2026-09-17 建）：必须在 build_satellite_pool 之前——轨B 与影子轨
    # 共用同一面板；重建器自带「已最新则跳过」守卫。[软]=失败不阻断（影子轨数据会停更一天）。
    ("面板刷新 rebuild_panels[软]", ["backtest/rebuild_panels.py"], "--skip-panel" in sys.argv),
    # 影子轨 shadow_ret20（用户 2026-09-17 拍板 ③纸面跟踪）：BASE / λ0.2 / λ0.3 三臂日度记录，
    # 生产 composite 不动。产出 backtest/shadow_ret20/{ledger.csv,daily_metrics.jsonl}。
    ("影子轨 shadow_ret20[软]", ["backtest/shadow_ret20.py"], "--skip-shadow" in sys.argv),
    ("双卫星池 build_satellite_pool", ["backtest/build_satellite_pool.py"], False),
    ("三轨信号 signal_satellite", ["backtest/signal_satellite_0913.py"], False),
    ("KHunter 模拟盘A khunter_paper", ["khunter_paper_20260903.py"], False),
    ("KHunter 模拟盘C khunter_paper_c", ["khunter_paper_20260903.py", "--state", "khunter_paper_state_c", "--rsi-sell", "50"], False),
    ("A5 打板模拟盘 a5_paper", ["backtest/a5_paper_0914.py"], False),
    # 黄金卫星叠加模拟盘（R-gold-sat-0917 · 2026-09-17 用户拍板投产）：轨B 内划出 10%（6800）
    # 买入 sh518880 买入持有（B&H），并把黄金腿镜像成轨B 的一个 position。**必须在 satellite_paper 之前**
    # ——satellite_paper 的 mark 循环会逐只 load_px(code) 取价 → 黄金市值自动进轨B 净值（总敞口保持 CAP_B）。
    # [软]=失败不阻断主链；--skip-gold 跳过。
    ("黄金卫星模拟盘 gold_sat_paper[软]", ["backtest/gold_sat_paper.py"], "--skip-gold" in sys.argv),
    ("双卫星模拟盘 satellite_paper", ["backtest/satellite_paper_0914.py"], False),
    # ret20 倾斜臂模拟盘（R-ret20-paper-0917 · 2026-09-17 用户拍板 #2/#4「投产并加模拟盘」）
    # 形态：**不改生产 composite**（冻结引擎原样 = BASE）；λ0.2 / λ0.3 各以 68,000 **同额纯对照账户**落地，
    #       零实盘资金申领 → 逐日 A/B 可比、不与轨B 抢配额。信号唯一来源 = shadow_ret20/state.json 的当日臂清单。
    #       毕业首检 2026-10-15（NAV≥BASE 臂 / 月多数正 / 相对回撤≤BASE+5pp），过门后才由用户拍板给配额。
    # [软]=失败不阻断主链；--skip-ret20 跳过。
    ("ret20 倾斜臂模拟盘 ret20_paper[软]", ["backtest/ret20_paper.py"], "--skip-ret20" in sys.argv),
    # 基金主仓（轨C FB3-H20）模拟盘——补齐「三轨模拟盘」最后一块（2026-09-14 用户指出缺）
    ("基金主仓模拟盘 fund_paper[软]", ["backtest/fund_paper_0914.py"], False),
    ("pct40 出场执行 pct40_exit", ["backtest/pct40_exit_apply.py"], False),
    ("pct40 对照账本 exit_control", ["backtest/exit_control_0915.py"], False),
    ("KHunter 模拟盘快照 khunter_snapshot", ["khunter_paper_snapshot.py"], False),
    # A5 打板实验盘（看板「打板族」视图的数据源）——必须在 build_dual_system 之前跑；[软]=失败不阻断主链
    # 2026-09-14 补：此前该流水线未接入每日链 → 看板 A5 卡停在 as_of 09-10（持仓只显示 1 只），
    # 用户据此提问「A5 命中这么多，模拟盘为什么只有一只」。顺序=扫描→数据桥→复盘。
    # 反向筛回避资产日更（R-daban-negscreen-0919 · 2026-09-20 用户批准）：A5 反向筛闸门的资产
    # （kv 面板 → 10 臂信号 → block9/block10 回避掩码）随 data_full 推进。**必须在 A5 扫描之前**——
    # 不建这步，闸门覆盖会停在资产末日（2026-09-11 实测）→「闸门开了但拦不到东西」。
    # 历史行逐位保留 + 漂移即中止：data_full 历史复权再被修订时不会 silent 改写已验证决策
    # （2026-09-20 实测：data_full 历史价 09-13 后被复权重述，1229/3960 股 ±1%）。
    # 无新交易日时秒退（不写盘）；[软]=失败不阻断主链（闸门退回上一份资产 + 扫描器打 !! 告警）。
    ("反向筛资产日更 revscreen_regen[软]", ["backtest/revscreen_regen.py"], "--skip-rev" in sys.argv),
    # 潜龙出海族改造策略 C1 臂模拟盘（R-sharesweb-0921f · 用户 2026-09-21 批准投产，与 Khunter 并行）
    # 策略：超跌 ret20(T-1)<=-7.31% + 低吸 T+1开盘gap[-5%,-2%] + 熊市门 HS300(T)<MA20(T)，
    #       共有滤网 非ST/流通市值50-200亿/量比>=1.2/换手5-10%；T+1开盘买、T+1收盘卖。
    # 与 Khunter 并行依据（已实测重叠）：C1 信号日落入 Khunter 合格池比例中位 0.0%、
    #       两门 Jaccard 0.462 → 真分散。
    # ⚠ 已知缺陷（预注册 PRE-REGISTRATION_20260921_qlch_paper.md）：
    #   ① 50bp 成本门实质未过（★197 修正后按天等权持仓日净均仅 +0.014%、全期年化 -0.42%）
    #   ② 熊市门为样本内选择（OOS 2022-2026 5/5 正、衰减 23%，仍属事后）
    #   ③ 年化 11.78%（含国债ETF现金叠加）< 12% 毕业门
    #   → 本账户为**影子/模拟性质**，毕业门前不申领实盘资金；QLCH_CASH=1 可开空仓期国债ETF叠加。
    # [软]=失败不阻断主链；--skip-qlch 跳过。
    ("超跌低开低吸-旧基线 qlch_paper[软]", ["backtest/qlch_paper_20260921.py"], "--skip-qlch" in sys.argv),
    # 潜龙 B4 对照轨（R-qlch-filter-0921k · 2026-09-21 用户批准）：与 C1 基线并行跑同一段前向数据，
    # 在封存集上做头对头，而不是现在挑一个。
    # 差异：市值/换手 绝对区间 → 当日横截面分位带（市值[.20,.70] / 换手[.40,.80]）。
    # 依据：分层分解定位膨胀源=市值(1.73)/换手(2.02)；分位化后完整信号两段比 2.46→1.49（首次过 1.5 门），
    #       训练窗夏普 0.894→1.838、年化 16.18%→41.85%。
    # ⚠ 风险已在报告明示：稳定性恰在门线(1.49 vs 1.5)、仍属训练窗选型、改动了策略骨架（共有滤网）。
    # [软]=失败不阻断主链；--skip-qlchb4 跳过。
    ("超跌低开低吸-B4无上限 qlch_paper_b4[软]", ["backtest/qlch_paper_20260921.py", "--variant", "B4"], "--skip-qlchb4" in sys.argv),
    # 潜龙 B4+K=3 轨（R-qlch-poscap-0921l · 2026-09-21 用户批准）：单票权重上限 1/3，未用资金持国债ETF。
    # 目的：消掉「单票满仓」（B4 现口径下 248 天单只股票满仓、贡献 43.3% 总收益）。
    # 实测（20bp+现金）：年化 33.35%→24.97%（−8.4pp），但夏普 1.341→1.474、回撤 −22.90%→−15.47%、
    #   逐年双口径一致性 7/9→9/9、2026 单笔 −0.620%→+0.378%。50bp：夏普 0.646→0.804、回撤 −38.6%→−17.2%。
    # ⚠ 预注册年化门（≥0.8×基线）未过 → 按 §五.1 持仓上限**判作废**；本轨仅为封存集三方头对头而设，非采纳。
    # [软]=失败不阻断主链；--skip-qlchk3 跳过。
    # ★ 2026-09-21 用户拍板投产（命名「超跌低开低吸」）：B4 分位滤网 + 单票上限 1/3。
    #   ⚠ 保留 [软] 执行是工程判断（新模块首个稳定周后再硬化）——不影响投产状态：
    #   本轨每日运行、写入 state、出现在看板「🏷 超跌低开低吸」组，并输出今日收盘候选。
    #   硬化的代价：失败会阻断其后的看板重建；故先软一周。
    ("超跌低开低吸-B4K3 qlch_paper_b4k3[软]", ["backtest/qlch_paper_20260921.py", "--variant", "B4", "--maxpos", "3"], "--skip-qlchk3" in sys.argv),
    # 超跌低吸-B4K3主板轨（R-qlch-mainboard-0921m · 2026-09-21 用户批准预注册）：
    # 与第 29 步（B4K3 全池）**唯一差异 = 池**，构成单变量头对头。
    # 真主板 = sh600/601/603/605 + sz000/001/002/003（剔科创板 688，20% 涨跌幅）。
    # 依据：科创板剔除影响逐臂不同（B4 年化 −10.56pp / C1 现生产 +3.84pp），不能一刀切，须按臂判定。
    # 预注册 §三 声明：主板切片已被读过，不追溯为预注册；主板问题一律交封存集判定（§五 七门）。
    # [软]=失败不阻断主链；--skip-qlchmb 跳过。
    ("超跌低开低吸-B4K3主板 qlch_paper_b4k3mb[软]", ["backtest/qlch_paper_20260921.py", "--variant", "B4", "--maxpos", "3", "--mainboard"], "--skip-qlchmb" in sys.argv),
    # 候选臂挂前向采集轨（R-qlch-sealed-0922 · 2026-09-22 用户批准）：
    #   封存集 = 2026-09-22 起前向数据，毕业门见 PRE-REGISTRATION_20260921_qlch_paper.md §七（10 道 · 需 ≥60 交易日）
    #   ⚠ 只采集不申领资金；[软]=失败不阻断主链；--skip-qlchg60 / --skip-qlchcb 跳过
    ("超跌低开低吸-候选MA60门 qlch_paper_g60[软]", ["backtest/qlch_paper_20260921.py", "--variant", "B4", "--maxpos", "3", "--gate", "60"], "--skip-qlchg60" in sys.argv),
    ("超跌低开低吸-候选综合分 qlch_paper_cb[软]", ["backtest/qlch_paper_20260921.py", "--variant", "B4", "--maxpos", "3", "--select", "combo"], "--skip-qlchcb" in sys.argv),
    ("A5 打板实验盘扫描 paper_daban_a5[软]", [str(_A5_EXT / "paper_daban_a5.py") if _A5_EXT.is_dir() else str(BASE / "backtest" / "a5_experiment" / "paper_daban_a5.py")], "--skip-a5" in sys.argv),
    ("A5 看板数据 build_a5_pool[软]", ["build_a5_pool.py"], "--skip-a5" in sys.argv),
    ("A5 复盘日志 build_a5_review[软]", ["build_a5_review.py"], "--skip-a5" in sys.argv),
    # kxmm 市场情绪（恐贪指数+热力图）数据抓取——看板「市场情绪」视图数据源；[软]=失败不阻断，
    # 失败时保留上一份 kxmm_data.js（页面继续显示旧数据+日期）。R-kxmm-0917
    ("kxmm 市场情绪数据 fetch_kxmm[软]", ["backtest/fetch_kxmm.py"], "--skip-kxmm" in sys.argv),
    # 因子四检查日链闸（R-gatewiring-0918，2026-09-18 建）：跑便宜的两项——
    # ① warmup-check 于面板 mask（检出引擎域门切掉上市初期，陷阱 ★176）
    # ② finite-check 于日链状态 JSON 的数字叶子（拦 inf/NaN 静默污染，陷阱 ★178）
    # 仅 FAIL 时非零（FAIL 会打印到日志，但 [软] 语义下不阻断主链）；--skip-gate 跳过。
    ("因子检查闸 factor_gate_daily[软]", ["backtest/factor_gate_daily.py"], "--skip-gate" in sys.argv),
    ("看板重建 build_dual_system", ["build_dual_system.py"], False),
    ("部署 gh-pages", ["_deploy_fundline_0911.py"], "--skip-deploy" in sys.argv),
]
# ---- 数据步专用环境：显式禁代理 ----
# 2026-09-15 根因修复：本机代理（127.0.0.1:随机端口，VPN/Clash 类）会抖动；akshare 内部
# requests **不带 timeout**（stock_zh_a_short 等），代理一挂/半死 → 复权检测整段永久阻塞
# （0914 卡 52min / 0915 卡 76min 即此）。项目对腾讯/东财本就 `proxies=None` 直连，此处把
# 数据步的进程环境也隔离掉，源头消除依赖。（git push 等步骤仍用默认环境，避免影响 GitHub 访问）
import os as _os
NO_PROXY_ENV = {**_os.environ, "HTTP_PROXY": "", "HTTPS_PROXY": "", "http_proxy": "", "https_proxy": "",
                "NO_PROXY": "*", "no_proxy": "*"}

# ---- gushi 策略股池采集（R-gushi-simple-0918：单点放链尾·唯一采集点）----
# 用户 2026-09-17 夜拍板原话：「你修改下午三点半收盘任务，加在最后跑不就行了，为什么非要新建？」
# 对。原实现本来就在链尾；我上一轮却去试新建 16:20 定时器（被系统拒：本会话本身是定时任务会话），
# 被拒后又改成「链首试采 + 链尾正式」双入口 —— 用错的复杂度绕一个不需要绕的问题。
# 链首那次恒在 ~15:31，早于站点当日数据上线时刻（实测最早 16:22：2026-09-14 trading_date=当天
# / is_today=true / role=vip）约 51 分钟 → 必然空手，纯废动作 + 每天多刷一次假告警。已删。
# 现状：全链只剩这一处采集（本脚本第 ~210 行），位置 = STEPS 循环之后（= 「加在最后」）。
# 残留风险（待办，不在本次改动内）：链尾 ~16:38 距 VIP 到期 ~17:38 仅 ~59 分钟安全边际，链被
#   fullpool_guard 拖长（1-2h 全量补数）时可能跨过到期点 → role 非 vip → 拒绝落盘 → 当日丢失。
#   正确解法是把本步前置到「数据更新」之后（那时已能判交易日，时刻也早得多），但不可前置到闸门
#   之前（闸门在链首 sys.exit，周末/非交易日不应跑采集）。
# 非致命：CDP 离线 / 未登录 / 依赖缺失都不阻断主链。

t0 = time.time()
fails = []
soft_fails = []   # [软] 步骤失败清单：只报告、不改退出码（2026-09-22 用户批准补可见性）


def _gushi_py():
    for p in (PY, r"D:/Tools/venvs/pandadata/Scripts/python.exe"):
        try:
            if subprocess.run([p, "-c", "import websockets"], capture_output=True).returncode == 0:
                return p
        except FileNotFoundError:
            continue
    return None


for name, args, skip in STEPS:
    if skip:
        print(f"[skip] {name}", flush=True)
        continue
    print(f"\n========== {name} ==========", flush=True)
    _env = NO_PROXY_ENV if name.startswith("数据更新") else None   # 数据步禁代理（防代理抖动阻塞）
    r = subprocess.run([PY] + args, cwd=str(BASE), env=_env)
    # 2026-09-16：原生崩溃（Windows 0xC0000005 访问违规 = 3221225477 或 -1073741819）
    # 在本机被观测到在内存吃紧时**间歇**发生（build_short_pool 单独重跑即成功）。
    # 处置：回收内存 → 等 5s → 原样重试一次；仍失败才走原失败路径。
    if r.returncode in (3221225477, -1073741819):
        print(f"⚠️ {name} 原生崩溃 exit {r.returncode} —— 回收内存后重试一次", flush=True)
        import gc as _gc
        _gc.collect()
        time.sleep(5)
        r = subprocess.run([PY] + args, cwd=str(BASE), env=_env)
        print(f"   重试 {'成功 ✓' if r.returncode == 0 else f'仍失败 exit {r.returncode}'}", flush=True)
    if r.returncode == 3 and name.startswith("HS300 索引行"):
        if FORCE:
            print("⚠️ 今日 HS300 行情不可得（非交易日/数据源未就绪）—— --force 继续执行", flush=True)
            continue
        print("[skip] 非交易日：今日 HS300 行情不可得（数据源无今日行情）—— 数据步已完成，跳过后续步骤",
              flush=True)
        sys.exit(0)
    if r.returncode != 0:
        if name.endswith("[软]"):   # 软步骤：失败只告警，不阻断（如 A5 实验盘、影子轨）
            soft_fails.append(f"{name[:-3]}(exit {r.returncode})")
            print(f"⚠️ {name} 失败（exit {r.returncode}）—— 非致命，继续后续步骤", flush=True)
            continue
        fails.append(name)
        print(f"❌ {name} 失败（exit {r.returncode}）—— 中止后续步骤", flush=True)
        break

# ---- main 源码同步（看板产物，失败不阻断）----
if not fails and not NO_MAIN_PUSH:   # ⑤ 云端 Phase 1：只写 gh-pages，不写 main
    git = subprocess.run(["git", "add", "dual_system.html", "index.html", "short_pool.json",
                          "short_pool.js", "enhanced_data.js", "short_signals.js", "a5_pool.js",
                          "changelog.md", "changelog.html", "review_log.html",
                          "short_v3_fund_summary.json", "short_v3_fund_slip20_summary.json",
                          "backtest/satellite_pool.json",
                          "khunter_paper_state.json", "khunter_paper_state_c.json",
                          "backtest/a5_paper_state.json", "backtest/satellite_paper.json", "backtest/satellite_paper_a.json", "backtest/satellite_paper_b.json", "backtest/satellite_cfg.py",
                          "backtest/satellite_paper_init.json", "backtest/turn_shadow_state.json",
                          "backtest/gold_sat_paper.json", "backtest/gold_sat_paper.py",
                          "backtest/ret20_paper.py", "backtest/ret20_paper_l02.json", "backtest/ret20_paper_l03.json",
                          "backtest/shadow_ret20.py", "backtest/engine_anchor.json",
                          "backtest/shadow_ret20/ledger.csv", "backtest/shadow_ret20/state.json",
                          "backtest/shadow_ret20/daily_metrics.jsonl",
                          "backtest/pct40_exits_state.json", "backtest/exit_control_state.json",
                          "backtest/pct40_exit_apply.py", "backtest/exit_control_0915.py",
                          "backtest/fetch_val_daily.py", "backtest/signal_satellite_0913.py",
                          "backtest/build_satellite_pool.py", "backtest/fetch_kxmm.py",
                          "backtest/check_data_freshness.py", "backtest/fullpool_guard.py",
                          "backtest/_data_freshness.json", "backtest/verify_gold_sat_0917.json",
                          "backtest/ensure_index_row.py", "index_000300.csv",
                          # 2026-09-17 补：三个生产源文件此前从未进过链的 git 白名单（链只 add 产物）
                          "build_dual_system.py", "fetch_full_universe.py", "update_daily.py",
                          "kxmm_card.py", "kxmm_data.js",
                          "echarts.min.js", "daily_refresh.py",
                          # 2026-09-23 补：EM 批量兜底链的生产源文件（同样从未进链白名单 → 补丁不会被链提交）
                          "backtest/em_bulk_all.py", "backtest/em_bulk_snapshot.py",
                          "backtest/em_ulist_bulk.py", "backtest/em_leftover_fill.py",
                          "backtest/em_tencent_fill.py", "backtest/rebuild_v8cache.py"],
                         cwd=str(BASE), capture_output=True)
    if git.returncode == 0:
        c = subprocess.run(["git", "commit", "-m", f"chore(daily): {date.today()} 收盘刷新（池/信号/看板/复盘日志）"],
                           cwd=str(BASE), capture_output=True)
        if c.returncode == 0:
            p = subprocess.run(["git", "push", "origin", "main"], cwd=str(BASE), capture_output=True)
            print(f"[git] main 同步 {'✓' if p.returncode == 0 else '✗ ' + p.stderr.decode(errors='replace')[:100]}", flush=True)

# ---- 双卫星模拟盘记账（非致命：按「信号日次一交易日开盘价+20bp」口径自动建仓/日更净值，无需用户回填成交）----
if not fails:
    print(f"\n========== 双卫星模拟盘记账 satellite_paper ==========", flush=True)
    r = subprocess.run([PY, "backtest/satellite_paper_0914.py"],
                       cwd=str(BASE), capture_output=True, text=True, timeout=600)
    for ln in ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-8:]:
        print(ln, flush=True)



# ---- gushi 正式采集（链尾·唯一允许续费的入口）----
# 位置依据：链首试采（~15:31）大概率早于站点当日数据上线时刻（实测最早 16:22）；
#           链尾实测落在 ~16:38，落在「数据已上线」且「VIP 未到期」的窗口内。
# 扣分护栏全部在采集脚本内：_renewed_today() 每日 1 次上限 + 余额不足不扣分 + 非 vip 不落盘。
if not fails and not SKIP_GUSHI:
    _gp2 = _gushi_py()
    if _gp2:
        print(f"\n========== gushi 策略股池采集 collect_gushi（链尾·正式，可续费）==========", flush=True)
        # --renew：非 VIP 时自动续费 1 天卡（30 论坛积分）后继续采集（用户 2026-09-16 授权；护栏见脚本注释）
        r = subprocess.run([_gp2, "backtest/gushi_daily_collect.py", "--days", "10", "--renew"],
                           cwd=str(BASE), capture_output=True, text=True, timeout=900)
        for ln in ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-12:]:
            print(ln, flush=True)

_soft_note = f" · ⚠️ 软失败 {len(soft_fails)}：{', '.join(soft_fails)}" if soft_fails else ""
print(f"\n{'❌ 失败: ' + ', '.join(fails) if fails else '✅ 全链完成'}{_soft_note} · 总耗时 {time.time()-t0:.0f}s", flush=True)
sys.exit(1 if fails else 0)
