# -*- coding: utf-8 -*-
"""
统一配置模块（可移植性核心）
==========================
所有路径/数据源/阈值集中于此，支持环境变量覆盖，实现公司设备无损移植：
- 本目录结构随脚本整体拷贝即可（data/ data_tmp/ 相对 __file__）
- 外部依赖（westock CLI 路径）通过环境变量 WSTOCK_CLI 覆盖，默认自动探测
- 仪表盘模板通过 WB_SKILL_ROOT 指向 WorkBuddy 技能根目录，默认自动探测
"""
import os
import sys
import shutil
from pathlib import Path

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))

# ---- 数据目录（相对本脚本，整体拷贝即可移植）----
DATA_DIR = BASE_DIR / "data"          # 19 只关注标的日线
DATA_TMP = BASE_DIR / "data_tmp"      # 39 只验证标的日线
OUT_DIR = BASE_DIR                    # 产物输出目录（回测三件套/仪表盘/快照）

# ---- 外部依赖路径（可移植关键：全部支持环境变量覆盖）----
def _detect_westock_cli():
    """探测 westock-data CLI：1) 环境变量 2) PATH 3) 常见安装位置"""
    env = os.environ.get("WSTOCK_CLI")
    if env and Path(env).exists():
        return env
    p = shutil.which("westock-data")
    if p:
        return p
    # WorkBuddy 技能市场常见安装位置（自动探测多个候选）
    candidates = [
        Path.home() / ".workbuddy" / "plugins" / "marketplaces" / "experts" / "plugins"
        / "strategy-backtest-expert" / "skills" / "westock-data" / "scripts" / "index.js",
        Path.home() / ".workbuddy" / "skills" / "westock-data" / "scripts" / "index.js",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "westock-data"  # 兜底：假定在 PATH（公司设备可自行安装）

def _detect_skill_root():
    """探测 quant-backtest-lab 参考实现根目录（渲染仪表盘用）"""
    env = os.environ.get("WB_SKILL_ROOT")
    if env and Path(env).exists():
        return env
    candidates = [
        Path.home() / ".workbuddy" / "plugins" / "marketplaces" / "experts" / "plugins"
        / "strategy-backtest-expert" / "skills",
        Path.home() / ".workbuddy" / "skills",
    ]
    for c in candidates:
        if (c / "quant-backtest-lab" / "reference" / "render_dashboard.py").exists():
            return str(c)
    return str(Path.home() / ".workbuddy" / "skills")

WSTOCK_CLI = _detect_westock_cli()
SKILL_ROOT = _detect_skill_root()
QBL_REF = os.path.join(SKILL_ROOT, "quant-backtest-lab", "reference")

# ---- 数据溯源配置（方法论要点 1：来源等级制）----
# 来源等级：A=官方一手（交易所/指数编制方/公司披露）B=机构报告/转述 C=财经媒体/聚合
DATA_SOURCES = {
    "kline_stock_etf": {"name": "腾讯自选股行情接口（westock-data CLI）", "level": "A",
                        "note": "日线 qfq，交易所撮合数据"},
    "kline_fund": {"name": "通达信基金净值接口（setcode=33）", "level": "A",
                   "note": "场外基金净值 T-1 公布"},
    "research_news": {"name": "vault 研报情报 L1-L3", "level": "B",
                      "note": "人工分级，回测中静态赋值"},
}

# ---- 取数预算（方法论要点 2：防卡死）----
FETCH_BUDGET = {
    "max_sources_per_symbol": 2,   # 每个标的/指标最多尝试的来源数
    "max_attempts_per_source": 1,  # 每个来源最多抓取次数
    "timeout_seconds": 60,         # 单次抓取超时
    "fail_mark": "数据不足",        # 失败后的合法标记（禁止反复重试）
}

# ---- 置信度判定（方法论要点 3：机械规则）----
CONFIDENCE_RULES = {
    "coverage_high": 0.80,   # 覆盖率 >=80% 且方向一致 => 高置信
    "coverage_low": 0.60,    # 覆盖率 <60% => 低置信（数据不足）
    "direction_agree": 0.75, # 方向性指标中同色占比 >=75% => 高置信
}

def load_watchlist():
    """从 UNIVERSE 常量读取关注标的（与 weight_system_backtest 一致，避免重复维护）"""
    sys.path.insert(0, str(BASE_DIR))
    from weight_system_backtest import UNIVERSE
    return UNIVERSE
