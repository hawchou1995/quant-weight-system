# -*- coding: utf-8 -*-
"""
wind 2016-2021 前段数据 → 与 data_v2 现有 2021 起数据拼接（用户指定方案）
=========================================================================
- wind 拉 2016-01-01 ~ 2021-08-01 前段（存盘文件）→ 解析
- 与 data_v2/<code>.csv 现有（2021 起）拼接：按 date 合并、去重、升序
- 输出整体覆盖 data_v2/<code>.csv（2016 起完整序列）
用法：python merge_wind_prefix.py <code> <wind_file_path>
"""
import json, csv, os, sys

OUT = r"D:/Documents/Workbuddy/股票基金/_quant_weight_ref/data_v2"

def parse_wind(path):
    raw = open(path, encoding="utf-8", errors="ignore").read()
    i = raw.find('"rows"')
    if i < 0:
        return None
    arr = raw.find('[', i)
    depth = 0; end = len(raw)
    for j in range(arr, len(raw)):
        if raw[j] == '[':
            depth += 1
        elif raw[j] == ']':
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    try:
        rows = json.loads(raw[arr:end])
    except Exception:
        return None
    out = []
    for r in rows:
        try:
            # [TIME, OPEN, MATCH(close), HIGH, LOW, TURNOVER, VOLUME, ...]
            out.append([r[0][:10], float(r[1]), float(r[3]), float(r[4]), float(r[2]),
                        float(r[6] or 0), float(r[5] or 0)])
        except (ValueError, IndexError):
            pass
    return out

def main():
    code = sys.argv[1]
    wind_path = sys.argv[2]
    prefix = parse_wind(wind_path)
    if not prefix:
        print(f"{code}: wind 解析失败"); return
    # 读现有
    existing = {}
    csv_path = os.path.join(OUT, f"{code}.csv")
    if os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8") as f:
            for r in csv.reader(f):
                if r and r[0] != "date" and len(r) >= 7:
                    existing[r[0]] = [r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), float(r[6])]
    # 合并：wind 前段优先（同日期以 wind 为准，但 2021-08 后以现有为准）
    merged = {}
    for row in prefix:
        d = row[0]
        if d < "2021-08-01":
            merged[d] = row
    for d, row in existing.items():
        if d >= "2021-08-01":
            merged[d] = row
        elif d not in merged:
            merged[d] = row
    rows = sorted(merged.values(), key=lambda r: r[0])
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume", "amount"])
        w.writerows(rows)
    print(f"{code}: 拼接完成 {len(rows)} 根 {rows[0][0]} ~ {rows[-1][0]} (wind前段 {len(prefix)} 根, 现有 {len(existing)} 根)")

if __name__ == "__main__":
    main()
