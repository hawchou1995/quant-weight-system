# -*- coding: utf-8 -*-
"""
A5_tp8t2 实验系统 v1.3 — 每日扫描 + 模拟盘跟踪（2026-08-27 投产为实验形态）
（v1.1 新增 A2_tp3 回避清单：负期望警示信号，不单独交易）
（v1.3 · 2026-09-15 用户拍板：**双池独立滤网**——池A 超跌 ret20≤-7.31% / 池B 趋势 ADX14≥27.9，
  两因子各自独立成池、无共振交集（回测：线上基底 692 笔 +0.57%/笔 → 池A 282 笔 +1.37% 10/10 年正、
  池B 255 笔 +1.19% / 并集 396 笔 +1.19% 胜率 56.1% ≈38.6 笔/年；旧口径 11 笔 −1.71% 归档为 v1 记录）

回测口径（与 optimize_daban_v1.py 的 A5_tp8t2 配置完全一致）：
  信号：首板次日低开 2-5%（gap = open/prev_close - 1 ∈ [-5%, -2%]）
        首板日 = is_zt 且 非一字板 且 前一日非涨停
        过滤：首板日 rel_pos(60日) ≤ 0.5 且 成交额 ≥ 5000万 且 **双池至少命中其一**（v1.3）
  入场：T 日开盘价（低开确认后）
  出场（tp_t2）：T+1/T+2 日内 high ≥ 入场价×1.08 → 止盈价卖出（tp）
                否则收盘卖出（ts）；T+1 涨停→顺延 T+2；T+2 涨停→收盘强平（force）
  成本：买 0.525% / 卖 0.625%（模拟盘按实际成交价计算，不额外加滑点）
  池：主板+创业板（600/601/603/605/000/001/002/003/300/301），剔 ST/退/S开头

两阶段：
  阶段1（观察清单）：D 日首板 → 加入 watchlist（sb_date=D），D+1 若低开 2-5% 则入场
  阶段2（入场确认）：D 日检查 watchlist 中 sb_date=D-1 的标的，低开确认 → 记录入场

回避清单（v1.1 新增，A2_tp3 口径与回测逐位一致）：
  信号：首板次日低开 2-6%（gap ∈ [-6%, -2%]）+ 首板日 rel_pos ≤ 0.7 + 成交额 ≥ 5000万
  回测：胜率 63.1% 但单笔均值 -1.39%（负期望，盈亏比 0.29）→ 仅作警示：
        信号出现时回避或减仓，不单独交易；A5 入场信号若同时命中，严格执行 T+2 兜底

验证门（30 个已平仓信号后判定）——基准 = **全部信号口径**（模拟盘无每日≤5/情绪门控，与执行同口径，2026-08-28 修正）：
  胜率 ∈ [35%, 55%]（回测基准 46.1%）
  均值净收益 > -0.5%（回测基准 -0.17% @0.5%滑点）
  tp 出场占比 ∈ [12%, 32%]（回测基准 21.5%）
  三闸全过 → 边缘确认，可考虑小仓位实盘；均值 < -1% → 边缘证伪，停止

用法：python paper_daban_a5.py [--date YYYY-MM-DD]   （默认处理 data_full 最新交易日）
幂等：last_scan == 最新交易日 时只输出报告不重复处理
"""
import os, sys, json, csv, glob, time, re
from collections import Counter
import numpy as np

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = r"D:/Documents/Quant data/data_full"
NAMES_JSON = r"D:/Documents/Workbuddy/股票基金/quant-weight-system/data_full_names.json"
IND_JSON = r"D:/Documents/Workbuddy/股票基金/quant-weight-system/stock_industry.json"
STATE_FILE = os.path.join(BASE, "paper_state.json")
REPORT_DIR = os.path.join(BASE, "reports")

COST_BUY = 0.00525
COST_SELL = 0.00625
TP = 0.08
GAP_LO, GAP_HI = -0.05, -0.02
REL_POS_MAX = 0.5
AMT_MIN = 5e7
ROOM_MIN = 0.20   # F3 空间因子（9/3 过闸族）：首板日距前 60 日收盘高点 ≥20%（回测 G3_M3 唯一牛熊双过闸）
# v1.3 双池独立滤网（2026-09-15 用户拍板）：池A 超跌 / 池B 趋势——各自独立成池，不做共振交集
R20_MAX = -0.0731   # 池A：T-1 的 20 日收益 ≤ −7.31%（回测事件样本 q33；线上基底 +1.37%/笔，10/10 年正）
ADX_MIN = 27.9      # 池B：T-1 的 ADX14 ≥ 27.9（q67；线上基底 +1.19%/笔，8/10 年正）
TAIL_BYTES = 8000   # 尾部读取窗口（约 170 行，足够 60 日 rel_pos）

# A2_tp3 回避清单（负期望警示信号，不单独交易）——口径与 optimize_daban_v1.py A2_tp3 逐位一致
AVOID_GAP_LO, AVOID_GAP_HI = -0.06, -0.02
AVOID_REL_POS_MAX = 0.7
AVOID_AMT_MIN = 5e7

# ---------------- 池与名称 ----------------
def limit_thr(code):
    c = code[2:]
    return 0.195 if c.startswith(('300', '301')) else 0.095

def is_pool_code(code):
    if code.startswith('bj'):
        return False
    c = code[2:]
    if not c.isdigit():
        return False
    if c.startswith(('600', '601', '603', '605', '000', '001', '002', '003', '300', '301')):
        return True
    return False

def market_board(code):
    """按代码判定市场板块（2026-09-06 修复：与 build_a5_pool.market_board 同标准——
    board=主板/创业板/科创板；池内无北交所）。code 形如 sh600345 / sz001309。"""
    if not code or len(code) < 8:
        return "—"
    pref, num = code[:2], code[2:]
    if not num.isdigit():
        return "—"
    if pref == "sh":
        if num.startswith(("600", "601", "603", "605")):
            return "主板"
        if num.startswith(("688", "689")):
            return "科创板"
        return "沪市"
    if pref == "sz":
        if num.startswith(("000", "001", "002", "003")):
            return "主板"
        if num.startswith(("300", "301")):
            return "创业板"
        return "深市"
    if pref == "bj":
        return "北交所"
    return "—"

def is_st_name(name):
    if not name:
        return False
    n = str(name).strip()
    if 'ST' in n.upper() or '退' in n:
        return True
    if n.startswith('S'):
        return True
    return False

def load_names():
    try:
        with open(NAMES_JSON, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def load_industry():
    try:
        with open(IND_JSON, encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, dict) and 'map' in d:
            return d['map']  # 嵌套结构：{'map': {code6: 行业}}
        return d
    except Exception:
        return {}

# ---------------- 快速尾部读取 ----------------
def read_tail(path, n_bytes=TAIL_BYTES):
    """读 CSV 尾部，返回 (rows, at_start)。rows = [(date,o,h,l,c,v,a), ...] 旧→新
    a=amount（2026-09-04 起解析，供 compute_tail_features 单位自锚定判据用）"""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(0, 2)
            size = f.tell()
            start = max(0, size - n_bytes)
            f.seek(start)
            data = f.read()
    except Exception:
        return None, False
    lines = data.splitlines()
    if not lines:
        return None, False
    at_start = (start == 0)
    if not lines[0].startswith('date'):
        if at_start:
            return None, False
        # 窗口未含表头：补读首行
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                header = f.readline().strip()
        except Exception:
            return None, False
        lines = [header] + lines
    rows = []
    for ln in lines[1:]:
        parts = ln.split(',')
        if len(parts) < 6:
            continue
        d = parts[0].strip()
        if not DATE_RE.match(d):
            continue  # 尾部窗口首行可能是被截断的半行（日期字段变成价格），跳过
        try:
            o, h, l, c, v = (float(parts[1]), float(parts[2]), float(parts[3]),
                             float(parts[4]), float(parts[5]))
            a = float(parts[6]) if len(parts) > 6 and parts[6].strip() else 0.0
        except ValueError:
            continue
        rows.append((d, o, h, l, c, v, a))
    if len(rows) < 2:
        return None, at_start
    return rows, at_start

def _adx14(high, low, close, n):
    """Wilder ADX(14)（v1.3 池B 特征；与回测 daban_opt_0915.py 同实现）。n<28 返回全 NaN。"""
    adx = np.full(n, np.nan)
    if n < 28:
        return adx
    tr = np.zeros(n); pdm = np.zeros(n); ndm = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        ndm[i] = dn if (dn > up and dn > 0) else 0.0
    atr = np.full(n, np.nan); sp = np.full(n, np.nan); sn = np.full(n, np.nan)
    atr[14] = tr[1:15].sum(); sp[14] = pdm[1:15].sum(); sn[14] = ndm[1:15].sum()
    for i in range(15, n):
        atr[i] = atr[i - 1] - atr[i - 1] / 14 + tr[i]
        sp[i] = sp[i - 1] - sp[i - 1] / 14 + pdm[i]
        sn[i] = sn[i - 1] - sn[i - 1] / 14 + ndm[i]
    pdi = 100 * sp / np.where(atr > 0, atr, np.nan)
    ndi = 100 * sn / np.where(atr > 0, atr, np.nan)
    dx = 100 * np.abs(pdi - ndi) / np.where((pdi + ndi) > 0, pdi + ndi, np.nan)
    adx[27] = np.nanmean(dx[14:28])
    for i in range(28, n):
        adx[i] = (adx[i - 1] * 13 + dx[i]) / 14
    return adx


def compute_tail_features(rows, code):
    n = len(rows)
    close = np.array([r[4] for r in rows])
    open_ = np.array([r[1] for r in rows])
    high = np.array([r[2] for r in rows])
    low = np.array([r[3] for r in rows])
    vol = np.array([r[5] for r in rows])
    amt_raw = np.array([r[6] for r in rows])
    dates = [r[0] for r in rows]
    thr = limit_thr(code)
    prev_close = np.empty(n); prev_close[0] = np.nan; prev_close[1:] = close[:-1]
    ret = close / prev_close - 1
    is_zt = ret >= thr
    is_yz = (open_ == high) & (high == low) & (low == close) & is_zt
    rel_pos = np.full(n, np.nan)
    dist_high = np.full(n, np.nan)  # F3 空间因子（9/3 过闸族）：离前 60 日收盘高点的空间%（回测口径 (hi-close)/hi）
    if n >= 60:
        for i in range(59, n):
            lo = close[i-59:i+1].min()
            hi = close[i-59:i+1].max()
            rel_pos[i] = (close[i] - lo) / (hi - lo) if hi > lo else 0.5
            dist_high[i] = (hi - close[i]) / hi if hi > 0 else 0.0
    ret20 = np.full(n, np.nan)   # v1.3 池A：20 日收益
    if n >= 21:
        ret20[20:] = close[20:] / close[:-20] - 1
    adx14 = _adx14(high, low, close, n)   # v1.3 池B：ADX(14)
    amt = vol * close
    # 2026-09-04 修复（v2 全市场自锚定）：data_full 的 amount 2024-01-01 起全市场大面积=0，
    # volume 单位切换不统一——诊断 4987 只：4272 只在 2023-12/2024-01 缩 ~100 倍
    # （沪主板/深主板/创业板，股→手），888 只无切换（84% 科创板，保持股）；2024+ 新上市单位=手。
    # v1 板块限定（sh*/sz3*）有误：深市主板 sz0* 漏修、科创板 sh688 误乘 100。
    # v2 判据（tail 窗口内自锚定）：
    #   1) amount>0 的行保留真实值（绝不覆盖——sz000001 等 amount 全程真实，volume 后期才切手）；
    #   2) 2024+ 且 amount<=0 的行代理 = vol×close×mult，mult 优先取 amount>0 锚点行
    #      （amount/vol > close×50 → 手 ×100，否则 ×1），无锚点按板块兜底（sh688→×1，其余→×100）。
    mask = np.array([d >= '2024-01-01' for d in dates])
    if mask.any():
        pos = np.where(mask & (amt_raw > 0))[0]
        if len(pos) > 0:
            i = pos[0]
            mult = 100 if amt_raw[i] / vol[i] > close[i] * 50 else 1
        else:
            mult = 1 if code.startswith('sh688') else 100
        amt = np.where(mask & (amt_raw <= 0), vol * close * mult, amt_raw)
    return {'dates': dates, 'open': open_, 'high': high, 'low': low, 'close': close,
            'vol': vol, 'prev_close': prev_close, 'is_zt': is_zt, 'is_yz': is_yz,
            'rel_pos': rel_pos, 'dist_high': dist_high, 'ret20': ret20, 'adx14': adx14,
            'amt': amt, 'thr': thr}

def scan_avoid_list(feats, names, ind_map, D):
    """A2_tp3 回避清单（v1.1）：D-1 首板 + D 日低开 2-6% + rel_pos≤0.7 + 成交额≥5000万。

    回测口径（optimize_daban_v1.py A2_tp3）：胜率 63.1% 但单笔均值 -1.39%（负期望）。
    用途：负期望警示信号——信号出现时回避或减仓，不单独交易。
    注意：A5 入场信号（gap∈[-5%,-2%], rel_pos≤0.5）是 A2_tp3 信号的子集，
          即每个 A5 入场都同时命中回避清单，须严格执行 T+2 兜底。
    """
    out = []
    for code, feat in feats.items():
        if feat['dates'][-1] != D:
            continue
        i = len(feat['dates']) - 1
        if i < 1:
            continue
        j = i - 1  # 首板日 D-1
        if not feat['is_zt'][j]:
            continue
        if feat['is_yz'][j]:
            continue
        if j >= 1 and feat['is_zt'][j-1]:
            continue  # 前一日涨停 → 非首板
        rp = feat['rel_pos'][j]
        if rp == rp and rp > AVOID_REL_POS_MAX:
            continue
        if feat['amt'][j] < AVOID_AMT_MIN:
            continue
        o, pc = feat['open'][i], feat['prev_close'][i]
        if o <= 0 or pc <= 0:
            continue
        gap = o / pc - 1
        if not (AVOID_GAP_LO <= gap <= AVOID_GAP_HI):
            continue
        if feat['is_yz'][i]:
            continue  # 一字板（低开不成立）
        out.append({'code': code, 'name': names.get(code, code),
                    'ind': ind_map.get(code[2:], '其他'),
                    'sb_date': feat['dates'][j], 'entry_date': D,
                    'rel_pos': float(rp) if rp == rp else None,
                    'amt': float(feat['amt'][j]), 'gap': float(gap)})
    return out


def scan_zt_panorama(feats, names, ind_map, D, min_pct=9.5):
    """今日涨停全景（2026-09-05 用户需求）：D 日收盘涨幅 ≥9.5% 或封板的全部标的，
    含 A5 过闸命中标记（首板 + 非一字 + rel_pos≤0.5 + F3空间≥20% + 成交额≥5000万）。
    纯观察数据，不参与任何状态机；幂等刷新（每次扫描都覆盖当日快照）。"""
    out = []
    for code, feat in feats.items():
        if feat['dates'][-1] != D:
            continue
        i = len(feat['dates']) - 1
        pc = feat['prev_close'][i]
        c = feat['close'][i]
        if pc <= 0 or c <= 0:
            continue
        pct = c / pc - 1
        sealed = bool(feat['is_zt'][i])
        if not sealed and pct < min_pct / 100:
            continue
        yz = bool(feat['is_yz'][i])
        first_board = sealed and (i < 1 or not feat['is_zt'][i - 1])
        rp = feat['rel_pos'][i]
        dh = feat['dist_high'][i]
        amt = float(feat['amt'][i])
        r20 = feat['ret20'][i]
        adx = feat['adx14'][i]
        pool_hits = []
        if r20 == r20 and r20 <= R20_MAX:
            pool_hits.append('R20')
        if adx == adx and adx >= ADX_MIN:
            pool_hits.append('ADX')
        hit = bool(sealed and first_board and not yz
                   and (rp == rp and rp <= REL_POS_MAX)
                   and (dh == dh and dh >= ROOM_MIN)
                   and amt >= AMT_MIN and pool_hits)
        # 档位/建议（2026-09-05 用户需求：命中标签之外给操作建议）
        if hit:
            tier, advice = "观察", f"明日低开 2-5% 可入场（池：{'/'.join(pool_hits)}）"
        elif not sealed:
            tier, advice = "不追", "未封板"
        elif yz:
            tier, advice = "不追", "一字板不追"
        elif not first_board:
            tier, advice = "不追", "连板不追"
        else:
            reasons = []
            if r20 == r20 and r20 > R20_MAX and (adx != adx or adx < ADX_MIN):
                reasons.append(f"双池未命中(r20 {r20*100:+.1f}%需≤-7.31% / ADX {adx:.0f}需≥28)")
            if rp == rp and rp > REL_POS_MAX:
                reasons.append(f"位置偏高(rel {rp:.2f}>0.5)")
            if dh == dh and dh < ROOM_MIN:
                reasons.append(f"空间不足({dh * 100:.0f}%低于20%)")
            if amt < AMT_MIN:
                reasons.append(f"成交额不足({amt / 1e4:.0f}万低于5000万)")
            tier, advice = "不追", ("未过闸：" + "；".join(reasons)) if reasons else "未过闸"
        out.append({'code': code, 'name': names.get(code, code),
                    'board': market_board(code),
                    'ind': ind_map.get(code[2:], '其他'),
                    'pct': round(pct * 100, 2),
                    'close': round(float(c), 2),
                    'sealed': sealed, 'yz': yz, 'first_board': first_board,
                    'rel_pos': round(float(rp), 3) if rp == rp else None,
                    'dist_high': round(float(dh) * 100, 1) if dh == dh else None,
                    'amt': amt,
                    'pools': pool_hits,
                    'r20': round(float(r20) * 100, 2) if r20 == r20 else None,
                    'adx': round(float(adx), 1) if adx == adx else None,
                    'hit': hit,
                    'tier': tier, 'advice': advice})
    out.sort(key=lambda x: (-x['hit'], -x['pct']))
    return out


# ---------------- 状态 ----------------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {'watchlist': [], 'positions': [], 'closed': [], 'equity': [],
            'last_scan': None, 'created': time.strftime('%Y-%m-%d %H:%M:%S')}

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=1)

# ---------------- 核心逻辑 ----------------
def main():
    t0 = time.time()
    names = load_names()
    ind_map = load_industry()
    state = load_state()
    files = sorted(glob.glob(os.path.join(DATA_DIR, '*.csv')))

    # 一遍扫描：缓存特征 + 收集日期
    feats = {}
    all_dates = set()
    for fi, f in enumerate(files):
        code = os.path.basename(f)[:-4]
        if not is_pool_code(code):
            continue
        if is_st_name(names.get(code, '')):
            continue
        rows, at_start = read_tail(f)
        if rows is None:
            continue
        if len(rows) < 60 and not at_start:
            continue  # 无法确认总行数且尾部不足 60 行
        if len(rows) < 60 and at_start:
            continue  # 总行数 < 60（与回测一致跳过）
        feat = compute_tail_features(rows, code)
        feats[code] = feat
        all_dates.update(feat['dates'])
        if (fi + 1) % 2000 == 0:
            print(f'  扫描 {fi+1}/{len(files)} ...')
    print(f'  池内文件: {len(feats)}，扫描耗时 {time.time()-t0:.0f}s')

    dates_sorted = sorted(all_dates)
    if not dates_sorted:
        print('无数据'); return
    D = dates_sorted[-1]
    REQUEST_DATE = None
    if "--date" in sys.argv:
        REQUEST_DATE = sys.argv[sys.argv.index("--date") + 1]
        if REQUEST_DATE in dates_sorted:
            D = REQUEST_DATE
        else:
            print("请求的日期 %s 不在数据内（可用范围 %s ~ %s）"
                  % (REQUEST_DATE, dates_sorted[0], dates_sorted[-1]))
            return
    else:
        _rs0 = rev_screen.stats(D)
        if _rs0.get("stale"):
            print("  !! 反向筛闸门告警: %s 不在资产覆盖内（资产至 %s，缺口 %d 天）"
                  % (D, _rs0.get("asset_last"), _rs0.get("gap_days")))
    prev_dates = [d for d in dates_sorted if d < D]
    D1 = prev_dates[-1] if prev_dates else None
    print(f'  最新交易日 D={D}，前一交易日 D-1={D1}')

    # 今日涨停全景（2026-09-05 用户需求）：纯观察，幂等刷新（含已处理日的重跑）
    panorama = scan_zt_panorama(feats, names, ind_map, D)
    state['zt_panorama'] = {'date': D, 'stocks': panorama}
    print(f'  今日涨停全景（≥9.5%/封板）: {len(panorama)} 只，A5 命中 {sum(1 for s in panorama if s["hit"])} 只')

    # A2_tp3 回避清单（v1.1）：全市场扫描，负期望警示
    avoid_list = scan_avoid_list(feats, names, ind_map, D)
    print(f'  A2_tp3 回避清单（负期望警示）: {len(avoid_list)} 只')

    if state.get('last_scan') == D:
        print(f'  已处理过 {D}，幂等跳过（仅输出报告）')
        save_state(state)  # 2026-09-05：zt_panorama 幂等刷新也需落盘
        report(state, D, D1, avoid_list)
        return

    # ---- 阶段2：watchlist → 入场确认（sb_date == D-1 的标的，检查 D 日低开） ----
    new_positions = []
    kept_wl = []
    for w in state.get('watchlist', []):
        code = w['code']
        if w['sb_date'] != D1:
            if w['sb_date'] < D1:
                print(f'  [过期] {code} {w["name"]} 观察日 {w["sb_date"]} 已过，丢弃')
            else:
                kept_wl.append(w)  # 未来观察日（异常，保留）
            continue
        feat = feats.get(code)
        if feat is None or feat['dates'][-1] != D:
            print(f'  [停牌/无数据] {code} {w["name"]} 观察日 {w["sb_date"]} 无 {D} 数据，丢弃')
            continue
        i = feat['dates'].index(D)
        o, pc, v = feat['open'][i], feat['prev_close'][i], feat['vol'][i]
        if o <= 0 or pc <= 0 or v <= 0:
            print(f'  [无效数据] {code} {w["name"]} {D} 开盘/量异常，丢弃')
            continue
        gap = o / pc - 1
        if not (GAP_LO <= gap <= GAP_HI):
            print(f'  [未低开] {code} {w["name"]} {D} gap={gap*100:+.2f}% 不在 [{GAP_LO*100:.0f}%,{GAP_HI*100:.0f}%]，不入场')
            continue
        if feat['is_yz'][i]:
            print(f'  [一字板] {code} {w["name"]} {D} 一字板，不入场')
            continue
        pos = {'code': code, 'name': w['name'], 'ind': w['ind'],
               'sb_date': w['sb_date'], 'entry_date': D,
               'entry_px': float(o), 'gap': float(gap),
               'pools': w.get('pools', []),   # v1.3 入场来源池（归因用）
               'exit_stage': 1, 'status': 'open',
               'exit_date': None, 'exit_px': None, 'exit_reason': None,
               'raw_ret': None, 'net_ret': None}
        new_positions.append(pos)
        print(f'  [入场] {code} {w["name"]} {D} 开盘 {o:.2f} gap={gap*100:+.2f}%'
              f' 池={"/".join(pos["pools"]) or "—"}'
              f' ⚠ 命中 A2_tp3 回避清单（负期望警示，严格执行 T+2 兜底）')
    state['watchlist'] = kept_wl
    state['positions'].extend(new_positions)

    # ---- 出场处理：open 持仓按 tp_t2 规则 ----
    still_open = []
    for pos in state['positions']:
        if pos['status'] != 'open':
            still_open.append(pos)
            continue
        code = pos['code']
        feat = feats.get(code)
        if feat is None:
            still_open.append(pos)
            continue
        try:
            ei = feat['dates'].index(pos['entry_date'])
        except ValueError:
            still_open.append(pos)
            continue
        stage = pos['exit_stage']
        idx = ei + stage
        if idx >= len(feat['dates']):
            still_open.append(pos)  # 数据未到
            continue
        bar_date = feat['dates'][idx]
        if bar_date > D:
            still_open.append(pos)  # 该 bar 尚未发生
            continue
        # 处理出场
        epx = pos['entry_px']
        if feat['is_zt'][idx]:
            if stage == 1:
                pos['exit_stage'] = 2
                print(f'  [顺延] {code} {pos["name"]} T+1({bar_date}) 涨停，顺延 T+2')
                still_open.append(pos)
            else:
                spx = float(feat['close'][idx])
                reason = 'force'
                _close_pos(pos, bar_date, spx, reason)
                print(f'  [强平] {code} {pos["name"]} T+2({bar_date}) 涨停，收盘强平 {spx:.2f}')
                still_open.append(pos)  # 2026-08-28 修复：已平仓保留在 positions
        else:
            tp_px = epx * (1 + TP)
            if feat['high'][idx] >= tp_px:
                spx = tp_px
                reason = 'tp'
                _close_pos(pos, bar_date, spx, reason)
                print(f'  [止盈] {code} {pos["name"]} {bar_date} 冲高≥{tp_px:.2f}，{spx:.2f} 卖出')
                still_open.append(pos)  # 2026-08-28 修复：已平仓保留在 positions
            else:
                spx = float(feat['close'][idx])
                reason = 'ts'
                _close_pos(pos, bar_date, spx, reason)
                print(f'  [收盘卖] {code} {pos["name"]} {bar_date} 收盘 {spx:.2f} 卖出')
                still_open.append(pos)  # 2026-08-28 修复：已平仓保留在 positions
    state['positions'] = still_open

    # ---- 阶段1：新观察清单（D 日首板） ----
    new_wl = []
    for code, feat in feats.items():
        if feat['dates'][-1] != D:
            continue
        i = len(feat['dates']) - 1
        if not feat['is_zt'][i]:
            continue
        if feat['is_yz'][i]:
            continue
        if i < 1 or feat['is_zt'][i-1]:
            continue  # 前一日涨停 → 非首板
        rp = feat['rel_pos'][i]
        if rp == rp and rp > REL_POS_MAX:
            continue
        dh = feat['dist_high'][i]
        if dh == dh and dh < ROOM_MIN:
            continue  # F3 空间因子：首板日距前 60 日收盘高点 <20% → 不入观察清单（G3_M3 过闸族）
        if feat['amt'][i] < AMT_MIN:
            continue
        # v1.3 双池独立滤网（用户拍板：各自独立成池，不做交集）
        r20 = feat['ret20'][i]
        adx = feat['adx14'][i]
        pools = []
        if r20 == r20 and r20 <= R20_MAX:
            pools.append('R20')
        if adx == adx and adx >= ADX_MIN:
            pools.append('ADX')
        if not pools:
            continue  # 双池均未命中 → 不入观察清单
        new_wl.append({'code': code, 'name': names.get(code, code),
                       'ind': ind_map.get(code[2:], '其他'), 'sb_date': D,
                       'rel_pos': float(rp) if rp == rp else None,
                       'dist_high': float(dh) * 100 if dh == dh else None,  # 百分比单位（回测 0.2 → 20）
                       'amt': float(feat['amt'][i]),
                       'pools': pools,
                       'r20': round(float(r20) * 100, 2) if r20 == r20 else None,
                       'adx': round(float(adx), 1) if adx == adx else None})
    # 去重（已在 watchlist 中的不重复加）
    existing = {(w['code'], w['sb_date']) for w in state['watchlist']}
    new_wl = [w for w in new_wl if (w['code'], w['sb_date']) not in existing]
    state['watchlist'].extend(new_wl)
    _np = Counter('/'.join(w['pools']) for w in new_wl)
    print(f'  新观察清单（{D} 首板，明日低开 2-5% 则入场）: {len(new_wl)} 只（池: {dict(_np)}）')

    # ---- 净值曲线 ----
    nav = state['equity'][-1]['nav'] if state['equity'] else 1.0
    for pos in state['positions']:
        if pos['status'] == 'closed' and pos.get('_nav_applied') is not True:
            nav *= (1 + pos['net_ret'])
            pos['_nav_applied'] = True
    state['equity'].append({'date': D, 'nav': round(nav, 6)})

    state['last_scan'] = D
    save_state(state)
    print(f'  状态已保存，总耗时 {time.time()-t0:.0f}s')
    report(state, D, D1, avoid_list)

def _close_pos(pos, exit_date, exit_px, reason):
    pos['status'] = 'closed'
    pos['exit_date'] = exit_date
    pos['exit_px'] = float(exit_px)
    pos['exit_reason'] = reason
    raw = float(exit_px) / pos['entry_px'] - 1
    pos['raw_ret'] = raw
    pos['net_ret'] = (1 + raw) * (1 - COST_BUY) * (1 - COST_SELL) - 1

# ---------------- 报告 ----------------
def report(state, D, D1, avoid_list=None):
    os.makedirs(REPORT_DIR, exist_ok=True)
    closed_all = [p for p in state['positions'] if p['status'] == 'closed']
    closed = [p for p in closed_all if p.get('pools')]   # v1.3 新口径（有池标记）——验证门只计新口径
    v1_n = len(closed_all) - len(closed)                  # v1 旧口径归档（不计入新口径判定）
    open_pos = [p for p in state['positions'] if p['status'] == 'open']
    lines = []
    lines.append(f'# A5_tp8t2 实验系统 · 日报 {D}')
    lines.append('')
    lines.append(f'- 最新交易日：{D}（前一交易日 {D1}）')
    lines.append(f'- 观察清单 {len(state["watchlist"])} 只 · 持仓 {len(open_pos)} 只 · 已平仓 {len(closed_all)} 笔'
                 f'（新口径 {len(closed)} · v1 归档 {v1_n}）')
    lines.append('')
    lines.append('## 明日观察清单（今日首板，明日低开 2-5% 则入场）')
    lines.append('')
    if state['watchlist']:
        lines.append('| 代码 | 名称 | 行业 | 首板日 | 池 | rel_pos | r20 | ADX | 成交额(万) |')
        lines.append('|---|---|---|---|---|---|---|---|---|')
        for w in sorted(state['watchlist'], key=lambda x: -x['amt']):
            lines.append(f"| {w['code']} | {w['name']} | {w['ind']} | {w['sb_date']} | "
                         f"{'/'.join(w.get('pools', [])) or '—'} | {w['rel_pos']:.2f} | "
                         f"{w.get('r20', '') if w.get('r20') is not None else ''} | "
                         f"{w.get('adx', '') if w.get('adx') is not None else ''} | {w['amt']/1e4:.0f} |")
    else:
        lines.append('（无）')
    lines.append('')
    lines.append('## ⚠ A2_tp3 回避清单（负期望警示 · 不单独交易）')
    lines.append('')
    lines.append('今日满足 A2_tp3 信号（首板次日低开 2-6% + rel_pos≤0.7 + 成交额≥5000万）。')
    lines.append('回测：胜率 63.1% 但单笔均值 -1.39%（负期望，盈亏比 0.29）→ 信号出现时回避或减仓，不追高。')
    lines.append('')
    if avoid_list:
        lines.append('| 代码 | 名称 | 行业 | 首板日 | 今日gap | rel_pos | 成交额(万) |')
        lines.append('|---|---|---|---|---|---|---|')
        for a in sorted(avoid_list, key=lambda x: -x['amt']):
            lines.append(f"| {a['code']} | {a['name']} | {a['ind']} | {a['sb_date']} | "
                         f"{a['gap']*100:+.2f}% | {a['rel_pos']:.2f} | {a['amt']/1e4:.0f} |")
    else:
        lines.append('（无）')
    lines.append('')
    lines.append('## 持仓')
    lines.append('')
    if open_pos:
        lines.append('| 代码 | 名称 | 入场日 | 入场价 | gap | 池 | 出场阶段 |')
        lines.append('|---|---|---|---|---|---|---|')
        for p in open_pos:
            lines.append(f"| {p['code']} | {p['name']} | {p['entry_date']} | {p['entry_px']:.2f} | "
                         f"{p['gap']*100:+.2f}% | {'/'.join(p.get('pools', [])) or '—'} | T+{p['exit_stage']} |")
    else:
        lines.append('（无）')
    lines.append('')
    lines.append('## 已平仓（累计）')
    lines.append('')
    if closed:
        lines.append('| 代码 | 名称 | 入场日 | 出场日 | 入场价 | 出场价 | 原因 | 池 | 净收益 |')
        lines.append('|---|---|---|---|---|---|---|---|---|')
        for p in closed:
            lines.append(f"| {p['code']} | {p['name']} | {p['entry_date']} | {p['exit_date']} | "
                         f"{p['entry_px']:.2f} | {p['exit_px']:.2f} | {p['exit_reason']} | "
                         f"{'/'.join(p.get('pools', [])) or 'v1旧口径'} | {p['net_ret']*100:+.2f}% |")
    else:
        lines.append('（无）')
    lines.append('')
    lines.append('## 验证统计（vs 回测基准）')
    lines.append('')
    lines.append('> 验证门口径 v1.3（2026-09-15 用户拍板）：**只计新口径交易**（入场带池标记）；'
                 'v1 旧口径记录归档不混算。新基准 = 双池并集（线上基底 2016-2026）：'
                 '胜率 56.1% / 均值 +1.19% / tp 占比 25.0%。')
    lines.append('')
    if v1_n:
        lines.append(f'- v1 旧口径归档：{v1_n} 笔（均值 {np.mean([p["net_ret"] for p in closed_all if not p.get("pools")])*100:+.2f}%，不计入下述判定）')
        lines.append('')
    if closed:
        rets = np.array([p['net_ret'] for p in closed])
        raw = np.array([p['raw_ret'] for p in closed])
        wr = float((rets > 0).mean())
        tp_ratio = float(np.mean([p['exit_reason'] == 'tp' for p in closed]))
        lines.append(f'- 信号数（新口径）：{len(closed)}（验证门需 ≥30）')
        lines.append(f'- 胜率：{wr*100:.1f}%（基准 56.1%，闸 [46%, 66%]）')
        lines.append(f'- 均值净收益：{rets.mean()*100:+.2f}%（基准 +1.19%，闸 >+0.5%）')
        lines.append(f'- 均值毛收益：{raw.mean()*100:+.2f}%')
        lines.append(f'- tp 出场占比：{tp_ratio*100:.1f}%（基准 25.0%，闸 [15%, 35%]）')
        lines.append(f'- 净值：{state["equity"][-1]["nav"]:.4f}（全部已平仓复利）')
        verdict = []
        if len(closed) >= 30:
            if wr < 0.46 or wr > 0.66: verdict.append('胜率出闸')
            if rets.mean() <= 0.005: verdict.append('均值净收益出闸')
            if tp_ratio < 0.15 or tp_ratio > 0.35: verdict.append('tp占比出闸')
            if not verdict:
                lines.append('- **判定：三闸全过 → 边缘确认，可考虑小仓位实盘**')
            else:
                lines.append(f'- **判定：未过闸（{", ".join(verdict)}）→ 继续观察**')
            if rets.mean() < -0.01:
                lines.append('- **⚠ 均值 < -1% 且 n≥30 → 边缘证伪，建议停止（v1.2 停止线条款）**')
        else:
            lines.append(f'- 判定：信号不足（{len(closed)}/30），继续积累（新口径自 2026-09-15 起计）')
    else:
        lines.append('（新口径尚无平仓记录；v1 归档见上）')
    lines.append('')
    lines.append('---')
    lines.append('*A5_tp8t2 实验系统 v1.3（双池独立滤网：池A 超跌 R20 / 池B 趋势 ADX；含 A2_tp3 回避清单）· '
                 '口径见 spec_A5_tp8t2.md · 模拟盘仅供边缘验证，非实盘指令*')
    txt = '\n'.join(lines)
    rp = os.path.join(REPORT_DIR, f'report_{D}.md')
    with open(rp, 'w', encoding='utf-8') as f:
        f.write(txt)
    print(txt)
    print(f'\n报告已写入 {rp}')

if __name__ == '__main__':
    main()
