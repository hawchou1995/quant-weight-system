# -*- coding: utf-8 -*-
"""P2：修正 gushi 采集脚本「登录态异常」误诊文案（R-gushi-early-0917）

现场证据（2026-09-17 夜实测）：
  链首试采（15:31 语义）时站点返回 HTML 错误页（`Unexpected token '<', "<!DOCTYPE "`），
  脚本把「全通道失败」统一归因为 `[WARN] 登录态异常——请在自动化窗口登录一次 gushi`。
  这是**误诊**：登录态好的很，真实原因是「① 当日数据尚未上线（实测最早 16:22 才有）
  或 ② 待采日期含未来交易日，站点对越界日期返回 HTML 错误页」。
  假告警每天刷会把真问题淹没（狼来了）。改为按本地时刻分场景提示。
"""
import sys
import py_compile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
P = BASE / "backtest" / "gushi_daily_collect.py"
t = P.read_text(encoding="utf-8")

if "站点当日数据实测**最早 16:22**" in t:
    print("  [skip] P2（已打过）")
else:
    old = (
        '        print("[WARN] 登录态异常——请在自动化窗口（profile D:/Tools/chrome-auto-profile）登录一次 gushi；"\n'
        '              "登录态会持久保存，之后无需再操作")\n'
    )
    if t.count(old) != 1:
        print(f"  [FAIL] 锚点命中 {t.count(old)} 次（期望 1）")
        sys.exit(1)
    new = (
        '        # ⚠ 2026-09-17 修：原文案一律归因「登录态异常」是**误诊**（实测链首 15:31 试采时\n'
        '        #   站点当日数据尚未上线 → 返回 HTML 错误页 → 全通道失败，与登录无关）。\n'
        '        #   按本地时刻分场景提示，避免每天刷假告警把真问题淹没。\n'
        '        _hhmm = int(time.strftime("%H%M"))\n'
        '        if _hhmm < 1630:\n'
        '            print("[WARN] 全部通道未取到数据——当前 %s，站点当日数据实测**最早 16:22** 才上线"\n'
        '                  "（2026-09-14 实测 trading_date=当天 / is_today=true），此刻空手属正常，"\n'
        '                  "正式采集请等收盘后 ~16:30 再跑。" % time.strftime("%H:%M"))\n'
        '        else:\n'
        '            print("[WARN] 全部通道未取到数据——已过 16:30 仍空手：先排除「待采日期含未来交易日」"\n'
        '                  "（站点对越界日期返回 HTML 错误页）；若日期正常则才是登录态问题——"\n'
        '                  "请在自动化窗口（profile D:/Tools/chrome-auto-profile）登录一次 gushi，"\n'
        '                  "登录态会持久保存，之后无需再操作")'
    )
    P.write_text(t.replace(old, new), encoding="utf-8")
    print("  [ok]   P2 误诊文案修正")

try:
    py_compile.compile(str(P), doraise=True)
    print("  [ok]   编译校验")
except Exception as e:
    print(f"  [FAIL] {type(e).__name__}: {e}")
    sys.exit(1)
print("总结论：✅ 落地")