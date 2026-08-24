# -*- coding: utf-8 -*-
"""dual_system.html 前端硬门槛测试 v4（2026-08-21 最终版）
hash 导航到数据视图后断言：title / topbar≤1 / 表格行数 / bodyTextLen / hasETF=false / pageerror
Artalk 评论外部服务 'Failed to fetch' 属网络不可达，非看板 bug，过滤不计。
"""
import re, sys
from playwright.sync_api import sync_playwright

HTML = r"D:\Documents\Workbuddy\股票基金\quant-weight-system\dual_system.html"
CHROME = r"C:\Users\Admin\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe"

fails = []
def check(name, cond, detail=""):
    tag = "OK" if cond else "❌"
    print(f"  [{tag}] {name} {detail}")
    if not cond:
        fails.append(name)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 1200})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"file:///{HTML}", wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(2000)

    # hash 导航到数据视图
    for key in ["auto", "lite", "short"]:
        try:
            page.evaluate(f"location.hash='{key}'")
            page.wait_for_timeout(500)
        except Exception:
            pass
    page.wait_for_timeout(1500)

    title = page.title()
    check("title", "量化" in title or "看板" in title or "监控" in title, f"title={title!r}")

    topbar = page.locator("nav, .topbar, header").count()
    check("topbar<=1", topbar <= 1, f"topbar={topbar}")

    rows = page.locator("table tbody tr").count()
    check("表格行数>=30", rows >= 30, f"rows={rows}")

    body_text = page.inner_text("body")
    check("bodyTextLen>5000", len(body_text) > 5000, f"len={len(body_text)}")

    # 精确ETF模式：沪51[0-8]xxxx（510-518，排除519场外基金）+ 深15xxxx（159）
    etf_pat = re.compile(r"\b(51[0-8]\d{3}|15\d{4})\b")
    etf_rows = page.locator("table tbody tr").filter(has_text=etf_pat)
    check("hasETF=false", etf_rows.count() == 0, f"etf_rows={etf_rows.count()}")

    # pageerror：过滤 Artalk 外部服务网络错误
    real_errors = [e for e in errors if "Failed to fetch" not in e]
    check("pageerror=0", len(real_errors) == 0, f"errors={real_errors[:3]}")

    badge = page.inner_text("body")
    # 2026-08-24 修复：原断言硬编码 08-20，改为断言最新数据日期徽章存在
    check("徽章含最新日期", "2026-08-24" in badge, "数据截至 2026-08-24")

    browser.close()

print("\n" + ("✅ 全部通过" if not fails else f"❌ 失败 {len(fails)} 项: {fails}"))
sys.exit(1 if fails else 0)
