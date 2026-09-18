# -*- coding: utf-8 -*-
"""daily_refresh 执行序测试：打桩 subprocess.run → 跑完整模块逻辑 → 断言 gushi 是最后一步。

为什么需要：py_compile 只查语法不查名字。本文件今天被改坏三次（缺 # / 变量被卷走 /
indentation 崩），每次 py_compile 都过。故必须做**运行期**验证。
"""
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
P = r"D:/Documents/Workbuddy/股票基金/quant-weight-system/daily_refresh.py"

CALLS = []


class FakeCP:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def fake_run(cmd, *a, **k):
    CALLS.append(cmd if isinstance(cmd, list) else [str(cmd)])
    return FakeCP(0)


real_run = subprocess.run
subprocess.run = fake_run
try:
    src = open(P, encoding="utf-8").read()
    g = {"__name__": "__main__", "__file__": P}
    try:
        exec(compile(src, P, "exec"), g)
    except SystemExit as e:
        print(f"[run] 模块干净退出（SystemExit {e.code}）")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[run] ❌ 运行期异常: {type(e).__name__}: {e}")
        sys.exit(1)
finally:
    subprocess.run = real_run

print(f"[run] 捕获到 {len(CALLS)} 次 subprocess 调用")

# 找出关键调用在序列里的位置
py = "python"
i_gushi = [i for i, c in enumerate(CALLS) if any("gushi_daily_collect" in str(x) for x in c)]
i_sat = [i for i, c in enumerate(CALLS) if any("satellite_paper_0914" in str(x) for x in c)]
i_build = [i for i, c in enumerate(CALLS) if any("build_dual_system" in str(x) for x in c)]
i_deploy = [i for i, c in enumerate(CALLS) if any("_deploy_fundline" in str(x) for x in c)]
i_gitpush = [i for i, c in enumerate(CALLS) if c[:2] == ["git", "push"]]

print(f"[idx] build_dual_system 序号 {i_build}")
print(f"[idx] _deploy_fundline  序号 {i_deploy}")
print(f"[idx] git push          序号 {i_gitpush}")
print(f"[idx] satellite_paper   序号 {i_sat}")
print(f"[idx] gushi_daily       序号 {i_gushi}")

checks = [
    ("gushi 只被调用一次", len(i_gushi) == 1),
    ("gushi 带 --renew", bool(i_gushi) and "--renew" in CALLS[i_gushi[0]]),
    ("gushi 在看板重建之后", bool(i_gushi and i_build) and i_gushi[0] > i_build[-1]),
    ("gushi 在部署之后", bool(i_gushi and i_deploy) and i_gushi[0] > i_deploy[-1]),
    ("gushi 在卫星记账之后", bool(i_gushi and i_sat) and i_gushi[0] > i_sat[-1]),
    ("gushi 是最后一个业务调用", bool(i_gushi) and i_gushi[0] == len(CALLS) - 1),
]
for k, v in checks:
    print(f"  [{'ok' if v else 'FAIL'}] {k}")
ok = all(v for _, v in checks)
print("RESULT: " + ("OK — gushi 确为链内最后一步" if ok else "FAIL"))
sys.exit(0 if ok else 1)
