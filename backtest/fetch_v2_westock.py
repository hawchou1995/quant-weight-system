# -*- coding: utf-8 -*-
"""
样本池 v2 数据拉取（退而求其次方案：2021-08 起，westock CLI 批量）
====================================================================
- 在票 90 只：westock kline --limit 2000（覆盖 2021-08 起 ~1210 根），批量多代码
- 批量输出格式：单表 | symbol | date | open | last | high | low | volume | amount | exchange |
  —— symbol 列分流；last 才是收盘价（列序铁律）
- 输出：data_v2/<code>.csv（date,open,high,low,close,volume,amount，date 去横线）
- 退市 10 只：wind 通道（后台 Agent）单独处理
"""
import subprocess, csv, os, time

WSTOCK_CLI = r"C:/Users/Admin/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/westock-data/scripts/index.js"
OUT_DIR = r"D:/Documents/Workbuddy/股票基金/_quant_weight_ref/data_v2"
os.makedirs(OUT_DIR, exist_ok=True)

POOL = {
    "AI算力": ["300308", "600498", "002281", "300502", "300394", "300570", "603083", "000988", "002902", "301205"],
    "半导体": ["688981", "002371", "603501", "603986", "300661", "688008", "603290", "002185", "002156", "600584"],
    "PCB": ["002463", "600183", "002384", "603228", "002916", "002938", "300476", "002815", "002913", "603920"],
    "白酒": ["600519", "000858", "000568", "600809", "002304", "000596", "603369", "600199", "600702", "600197"],
    "银行": ["601398", "600036", "601939", "000001", "601166", "600000", "600016", "601169", "601009", "002142"],
    "新能源": ["300750", "002594", "601012", "300274", "300014", "002074", "002709", "300438", "600499", "002407"],
    "医药": ["600276", "603259", "300760", "300122", "000661", "600196", "600436", "600557", "600566", "603707"],
    "资源": ["601088", "601899", "601225", "600188", "000983", "603993", "600111", "600489", "600392", "600988"],
    "消费": ["600887", "603288", "000333", "002714", "000895", "000651", "600690", "000848", "600597", "002216"],
}

def to_wind_prefix(code):
    return "sh" + code if code.startswith("6") else "sz" + code

def fetch_batch(codes):
    cmd = ["node", WSTOCK_CLI, "kline", ",".join(to_wind_prefix(c) for c in codes),
           "--period", "day", "--limit", "2000"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=120)
    return r.stdout

def parse_batch(text):
    """解析批量单表 → {code: rows}。列序：symbol|date|open|last|high|low|volume|amount|exchange"""
    data = {}
    for l in text.splitlines():
        if not l.strip().startswith("|"):
            continue
        cells = [c.strip() for c in l.strip("|").split("|")]
        if len(cells) < 9 or cells[0] == "symbol":
            continue
        sym, date = cells[0], cells[1]
        code = sym[2:]  # 去掉 sh/sz 前缀
        try:
            o, last, h, low, v, amt = float(cells[2]), float(cells[3]), float(cells[4]), float(cells[5]), float(cells[6]), float(cells[7])
        except ValueError:
            continue
        data.setdefault(code, []).append([date.replace("-", ""), o, h, low, last, v, amt])
    return data

def main():
    all_codes = [c for codes in POOL.values() for c in codes]
    print(f"在票标的 {len(all_codes)} 只，9 批拉取（2021-08 起 ~1210 根/只）")
    t0 = time.time()
    ok, fail = 0, []
    for sector, codes in POOL.items():
        print(f"\n=== {sector} ===")
        text = fetch_batch(codes)
        parsed = parse_batch(text)
        for code in codes:
            rows = parsed.get(code, [])
            if not rows:
                fail.append(code)
                print(f"  {code}: 无数据 ❌")
                continue
            rows.sort(key=lambda r: r[0])
            with open(os.path.join(OUT_DIR, f"{code}.csv"), "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["date", "open", "high", "low", "close", "volume", "amount"])
                w.writerows(rows)
            ok += 1
            print(f"  {code}: {len(rows)} 根, {rows[0][0]} ~ {rows[-1][0]}, 末日收盘 {rows[-1][4]}")
    print(f"\n✅ 成功 {ok} 只 / ❌ 失败 {len(fail)} 只 {fail}")
    print(f"耗时 {time.time()-t0:.0f}s")
    return ok, fail

if __name__ == "__main__":
    main()
