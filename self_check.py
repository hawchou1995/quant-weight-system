# -*- coding: utf-8 -*-
"""
移植自检脚本：公司设备拷贝后一键验证系统完整性
用法：python self_check.py  （期望全部 PASS）
"""
import os
import sys
import json
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")

print("=" * 60)
print("量化权重系统 v1.2 移植自检")
print("=" * 60)

# 1. 核心文件完整性
print("\n[1] 文件完整性")
required = [
    "config.py", "weight_system_backtest.py", "make_snapshot_v2.py",
    "validate_industry_v2.py", "render_dash_v2.py",
    "data", "data_tmp",
]
for f in required:
    check(f"存在 {f}", (BASE / f).exists(), f"缺少 {f}")

# 2. 数据完整性
print("\n[2] 数据完整性")
data_files = list((BASE / "data").glob("*.csv")) if (BASE / "data").exists() else []
tmp_files = list((BASE / "data_tmp").glob("*.csv")) if (BASE / "data_tmp").exists() else []
check(f"关注标的 {len(data_files)} 只（期望 19）", len(data_files) == 19, f"实际 {len(data_files)}")
check(f"验证标的 {len(tmp_files)} 只（期望 39）", len(tmp_files) == 39, f"实际 {len(tmp_files)}")

# 3. 依赖检查
print("\n[3] Python 依赖")
for m in ["pandas", "numpy"]:
    try:
        __import__(m)
        check(f"已安装 {m}", True)
    except ImportError:
        check(f"已安装 {m}", False, "pip install pandas numpy")

# 4. 硬编码路径检查（不应包含个人路径）
print("\n[4] 可移植性（无个人路径硬编码）")
hardcoded = []
for py in BASE.glob("*.py"):
    if py.name == "self_check.py":
        continue  # 自检脚本自身含检测字符串，跳过
    content = py.read_text(encoding="utf-8", errors="ignore")
    for bad in ["C:/Users/", "D:/Documents"]:
        if bad in content:
            hardcoded.append(f"{py.name}: {bad}")
check("无 C:/Users 或 D:/Documents 硬编码", not hardcoded, str(hardcoded))

# 5. 回归基准检查
print("\n[5] 回归基准（summary 数值）")
sum_path = BASE / "weight_system_summary.json"
if sum_path.exists():
    try:
        d = json.loads(sum_path.read_text(encoding="utf-8"))
        s = d["summary"]
        ret = s.get("total_return_pct")
        dd = s.get("max_drawdown_pct")
        check("组合总收益 ≈ 220.32%", ret is not None and abs(ret - 220.32) < 1.0, f"实际 {ret}%")
        check("最大回撤 ≈ 18.76%", dd is not None and abs(dd - 18.76) < 1.0, f"实际 {dd}%")
    except Exception as e:
        check("summary 可解析", False, str(e))
else:
    check("weight_system_summary.json 存在（先跑回测生成）", False)

# 6. 快照完整性
print("\n[6] 快照（含置信度+provenance）")
snap_path = BASE / "snapshot_20260810_v2.json"
if snap_path.exists():
    try:
        d = json.loads(snap_path.read_text(encoding="utf-8"))
        sigs = d.get("signals", [])
        check(f"快照 19 标的", len(sigs) == 19, f"实际 {len(sigs)}")
        has_conf = all("confidence" in s for s in sigs)
        has_prov = all("provenance" in s for s in sigs)
        check("全部含置信度字段", has_conf)
        check("全部含数据溯源(provenance)字段", has_prov)
    except Exception as e:
        check("快照可解析", False, str(e))
else:
    check("snapshot_20260810_v2.json 存在（先跑快照生成）", False)

print("\n" + "=" * 60)
print(f"结果：{PASS} PASS / {FAIL} FAIL")
if FAIL == 0:
    print("✅ 系统完整，可正常运行")
else:
    print("❌ 存在缺失，请按 vault 部署手册修复")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
