# -*- coding: utf-8 -*-
"""晴雨表集成冒烟测试 v1（2026-08-29）
在标准硬门槛（title/topbar/行数/bodyTextLen/hasETF/pageerror）基础上，
新增 #mkt-weather 卡片断言：卡片存在 / 情绪等级渲染 / 指数容器 / SVG 曲线 / 徽章。
Artalk 外部服务 'Failed to fetch' 属网络不可达，过滤不计。
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
    page.wait_for_timeout(3000)

    # hash 导航激活各数据视图（隐藏视图不计 inner_text；最后停留在数据密集视图）
    for key in ["sys-auto", "short", "a5", "review", "short"]:
        try:
            page.evaluate(f"location.hash='{key}'")
            page.wait_for_timeout(400)
        except Exception:
            pass
    page.wait_for_timeout(2000)

    # ---- 标准硬门槛 ----
    title = page.title()
    check("title", "量化" in title or "看板" in title or "监控" in title, f"title={title!r}")

    topbar = page.locator("nav, .topbar, header").count()
    check("topbar<=1", topbar <= 1, f"topbar={topbar}")

    rows = page.locator("table tbody tr").count()
    check("表格行数>=30", rows >= 30, f"rows={rows}")

    body_text = page.inner_text("body")
    check("bodyTextLen>5000", len(body_text) > 5000, f"len={len(body_text)}")

    etf_pat = re.compile(r"\b(51[0-8]\d{3}|15\d{4})\b")
    etf_rows = page.locator("table tbody tr").filter(has_text=etf_pat)
    check("hasETF=false", etf_rows.count() == 0, f"etf_rows={etf_rows.count()}")

    # ---- 晴雨表卡片 ----
    card = page.locator("#mkt-weather")
    check("晴雨表卡片存在", card.count() == 1)

    badge = page.locator("#mw-badge")
    badge_text = badge.inner_text().strip()
    check("徽章渲染", "实时" in badge_text or "静态" in badge_text or "精算" in badge_text, f"badge={badge_text!r}")

    summary = page.locator("#mw-summary")
    s_text = summary.inner_text()
    check("情绪等级渲染", "情绪" in s_text and "红盘" in s_text, f"summary={s_text[:60]!r}")

    idx = page.locator("#mw-idx")
    idx_count = idx.locator(".mw-idx-item").count()
    check("指数行情≥1", idx_count >= 1, f"idx_items={idx_count}")

    chart = page.locator("#mw-chart")
    chart_html = chart.inner_html()
    has_svg = "svg" in chart_html or "暂无日内曲线" in chart_html
    check("曲线渲染(svg/占位)", has_svg, f"chart_len={len(chart_html)}")

    # 静态数据落位（market_breadth.js 生效）
    mb = page.evaluate("window.MARKET_BREADTH ? {red: window.MARKET_BREADTH.latest.red, ts: window.MARKET_BREADTH.meta.ts} : null")
    check("静态数据加载", mb is not None and mb["red"] > 1000, f"MB={mb}")

    # ---- pageerror：过滤 Artalk 网络错误 ----
    real_errors = [e for e in errors if "Failed to fetch" not in e]
    check("pageerror=0", len(real_errors) == 0, f"errors={real_errors[:3]}")

    browser.close()

print("\n" + ("✅ 全部通过" if not fails else f"❌ 失败 {len(fails)} 项: {fails}"))
sys.exit(1 if fails else 0)
