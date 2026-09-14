# -*- coding: utf-8 -*-
"""生成 exit_lab_e37_0915.py：在 exit_lab_e6_0915.py 基础上换 E3/E7 臂"""
import io

src = open('exit_lab_e6_0915.py', encoding='utf-8').read()

old_hdr = '"""R-macd-kdj-event-0915 · E6 单阴背离组合级（轨B 载体）：BASE / pct40 / e6 / pct40+e6"""'
new_hdr = '"""R-macd-kdj-event-0915 · E3 修正案 + E7 轮2过门臂 组合级（轨B 载体）：BASE / pct40 / e3 / e7 / pct40+e3 / pct40+e7"""'
assert old_hdr in src, 'hdr'
src = src.replace(old_hdr, new_hdr)

i0 = src.index('# ---- E6 单阴背离')
i1 = src.index('log("轨B matrices ok")') + len('log("轨B matrices ok")')
new_block = '''# ---- E3/E7 顶背离（R-macd-kdj-event-0915：E3=首轮边缘修正案，E7=轮2 过门臂）：20日新高且 DIF 不新高；E7 叠加 J>80 ----
_SB = pd.DataFrame(close_ff)
_e12b = _SB.ewm(span=12, adjust=False).mean(); _e26b = _SB.ewm(span=26, adjust=False).mean()
DIFB = (_e12b - _e26b).to_numpy()
JB = J
_hi20 = _SB.rolling(20, min_periods=20).max().to_numpy()
is_hi = np.isclose(close_ff, _hi20) & np.isfinite(_hi20)
E3 = np.zeros((ND, NC), dtype=bool)
for j in range(NC):
    ih = np.where(is_hi[:, j])[0]
    for kk in range(1, len(ih)):
        t, tp = ih[kk], ih[kk - 1]
        if t - tp > 60:
            continue
        if np.isfinite(DIFB[t, j]) and np.isfinite(DIFB[tp, j]) and DIFB[t, j] < DIFB[tp, j]:
            E3[t, j] = True
E7 = E3 & (JB > 80)
log(f"轨B matrices ok | E3 {int(E3.sum())} / E7 {int(E7.sum())}")'''
src = src[:i0] + new_block + src[i1:]

old_trig = '''                elif exit_mode == "e6":    trig = bool(E6[di, jj])   # 单阴背离
                elif exit_mode == "pct40e6":
                    trig = ((np.isfinite(SPCT[di, jj]) and SPCT[di, jj] <= 0.60) or bool(E6[di, jj]))'''
new_trig = '''                elif exit_mode == "e3":    trig = bool(E3[di, jj])   # 顶背离
                elif exit_mode == "e7":    trig = bool(E7[di, jj])   # 顶背离 + J>80 共振
                elif exit_mode == "pct40e3":
                    trig = ((np.isfinite(SPCT[di, jj]) and SPCT[di, jj] <= 0.60) or bool(E3[di, jj]))
                elif exit_mode == "pct40e7":
                    trig = ((np.isfinite(SPCT[di, jj]) and SPCT[di, jj] <= 0.60) or bool(E7[di, jj]))'''
assert old_trig in src, 'trig'
src = src.replace(old_trig, new_trig)

old_modes = 'for mode in [None, "pct40", "e6", "pct40e6"]:'
new_modes = 'for mode in [None, "pct40", "e3", "e7", "pct40e3", "pct40e7"]:'
assert old_modes in src, 'modes'
src = src.replace(old_modes, new_modes)

src = src.replace("exit_lab_e6_0915.json", "exit_lab_e37_0915.json")
open('exit_lab_e37_0915.py', 'w', encoding='utf-8').write(src)
print('written exit_lab_e37_0915.py, lines:', len(src.splitlines()))
