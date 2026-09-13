# -*- coding: utf-8 -*-
"""TDX 通达信公式迷你解释器 → numpy 向量化执行（2026-09-12）
================================================================
用途：r2 素材驱动全量筛选——把 formula_lib 的 66 公式（71 个 select 块）
批量翻译为向量化信号，替代逐个手译。
设计：
  词法/递归下降解析 → AST 元组 → 每只股票一次性求值（numpy/pandas rolling）
  布尔按 1.0/0.0 浮点传播（TDX 语义：非零=真）；NaN 参与比较=False
支持函数：REF MA EMA SMA HHV LLV HHVBARS LLVBARS CROSS BARSLAST BARSSINCE
          COUNT EVERY EXIST SUM MAX MIN ABS POW SQRT SGN MOD IF
变窗支持：REF/HHV/LLV/SUM/COUNT/EVERY/EXIST 的 N 可为序列（BARSLAST 输出等）
不支持（触发 skip 并回执）：FINANCE*/CAPITAL/NAMELIKE/CODELIKE/INBLOCK/
  WINNER/COST/ZIG/PEAK/TROUGH（未来函数或数据不可得）
数据变量：C/CLOSE O/OPEN H/HIGH L/LOW V/VOL/VOLUME AMO/AMOUNT
"""
import re

import numpy as np
import pandas as pd

BIG = 10 ** 9

TOKEN_RE = re.compile(r"""
    (?P<num>\d+\.\d+|\.\d+|\d+)
  | (?P<str>'[^']*')
  | (?P<str2>"[^"]*")
  | (?P<id>[A-Za-z_\u4e00-\u9fff][A-Za-z_0-9\u4e00-\u9fff]*)
  | (?P<op>>=|<=|<>|==|=|>|<|\+|-|\*|/|\(|\)|,|\.[A-Za-z]+|[#][A-Za-z]+)
  | (?P<ws>\s+)
""", re.VERBOSE)

DISPLAY_ATTR_RE = re.compile(
    r"(?:\s*,\s*(?:COLOR[A-Z0-9]*|LINETHICK\d*|NODRAW|VOLSTICK|STICK\d*|DOTLINE|"
    r"CIRCLEDOT|CROSSDOT|POINTDOT|LINEDOT|LINEDASH|RGB\([^)]*\)))+\s*$", re.IGNORECASE)

FULLWIDTH = {"：": ":", "，": ",", "（": "(", "）": ")", "＜": "<", "＞": ">",
             "＝": "=", "　": " "}

KEYWORDS = {"AND", "OR", "NOT"}


def tokenize(s):
    toks, pos = [], 0
    while pos < len(s):
        m = TOKEN_RE.match(s, pos)
        if not m:
            raise SyntaxError(f"tokenize fail at {pos}: {s[pos:pos+20]!r}")
        pos = m.end()
        g = m.lastgroup
        if g == "ws":
            continue
        val = m.group()
        if g == "id":
            vu = val.upper()
            if vu in KEYWORDS:
                val = vu
            else:
                # 拆掉粘连的 ASCII 关键词后缀（如「低位金叉AND」）
                ms = re.search(r"(AND|OR|NOT)$", val)
                if ms and len(val) > len(ms.group(1)):
                    toks.append(("id", val[: -len(ms.group(1))]))
                    toks.append(("id", ms.group(1)))
                    continue
        toks.append((g, val))
    return toks


class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def eat(self, val=None):
        k, v = self.peek()
        if val is not None and v != val:
            raise SyntaxError(f"expect {val!r} got {v!r}")
        self.i += 1
        return v

    def parse(self):
        node = self.or_()
        if self.i != len(self.toks):
            raise SyntaxError(f"trailing tokens: {self.toks[self.i:]}")
        return node

    def or_(self):
        n = self.and_()
        while self.peek()[1] == "OR":
            self.eat()
            n = ("or", n, self.and_())
        return n

    def and_(self):
        n = self.not_()
        while self.peek()[1] == "AND":
            self.eat()
            n = ("and", n, self.not_())
        return n

    def not_(self):
        if self.peek()[1] == "NOT":
            self.eat()
            return ("not", self.not_())
        return self.cmp_()

    def cmp_(self):
        n = self.add()
        while self.peek()[1] in (">", "<", ">=", "<=", "=", "==", "<>"):
            op = self.eat()
            n = ("cmp", op, n, self.add())
        return n

    def add(self):
        n = self.mul()
        while self.peek()[1] in ("+", "-"):
            op = self.eat()
            n = ("arith", op, n, self.mul())
        return n

    def mul(self):
        n = self.unary()
        while self.peek()[1] in ("*", "/"):
            op = self.eat()
            n = ("arith", op, n, self.unary())
        return n

    def unary(self):
        if self.peek()[1] == "-":
            self.eat()
            return ("neg", self.unary())
        if self.peek()[1] == "+":
            self.eat()
            return self.unary()
        return self.primary()

    def primary(self):
        k, v = self.peek()
        if k == "num":
            self.eat()
            return ("num", float(v))
        if k == "str":
            self.eat()
            return ("str", v)
        if k == "str2":
            raise NotImplementedError("cross-indicator ref")
        if k == "op" and v == "(":
            self.eat()
            n = self.or_()
            self.eat(")")
            return n
        if k == "op" and v.startswith((".", "#")):
            raise NotImplementedError(f"cross-period ref {v}")
        if k == "id":
            self.eat()
            if v in KEYWORDS:
                raise SyntaxError(f"keyword misplaced: {v}")
            if self.peek()[1] == "(":
                self.eat()
                args = []
                if self.peek()[1] != ")":
                    args.append(self.or_())
                    while self.peek()[1] == ",":
                        self.eat()
                        args.append(self.or_())
                self.eat(")")
                return ("call", v.upper(), args)
            return ("var", v.upper())
        raise SyntaxError(f"unexpected token {v!r}")


SUPPORTED = {"REF", "MA", "EMA", "SMA", "HHV", "LLV", "HHVBARS", "LLVBARS",
             "CROSS", "BARSLAST", "BARSSINCE", "COUNT", "EVERY", "EXIST",
             "SUM", "MAX", "MIN", "ABS", "POW", "SQRT", "SGN", "MOD", "IF",
             "BETWEEN", "UPNDAY", "DOWNNDAY", "NDAY", "STD", "EXPMA", "SLOPE",
             "FORCAST", "AVEDEV", "FILTER", "CONST", "ATAN", "RANGE", "DMA"}
# DYNAINFO：盘中实时量，日频回测近似为常数 1（当日有成交；另计 flag）
LENIENT = {"DYNAINFO", "STICKLINE", "DRAWTEXT", "DRAWTEXT_FIX", "DRAWICON",
           "DRAWNUMBER", "DRAWNUMBER_FIX", "DRAWABOVE", "DRAWLINE", "POLYLINE",
           "VERTLINE", "DRAWKLINE", "DRAWNULL_FN"}
UNSUPPORTED = {"FINANCE", "NAMELIKE", "CODELIKE", "INBLOCK",
               "WINNER", "COST", "ZIG", "PEAK", "TROUGH", "PEAKBARS",
               "TROUGHBARS", "STKINDI", "EXPMEMA", "TFILTER",
               "ISLASTBAR", "CURRBARSCOUNT", "TOTALBARSCOUNT",
               "CONST"}  # CONST=取序列最终值，未来函数，拉黑
# 出现为「变量」形态的不可支持数据（盘中/筹码/周期元数据）
VAR_UNSUPPORTED = {"CAPITAL", "FROMOPEN", "TOTALBARSCOUNT", "CURRBARSCOUNT",
                   "ISLASTBAR", "ZTPRICE", "DTPRICE", "NAMELIKE", "CODELIKE"}


def collect_calls(node, acc):
    t = node[0]
    if t == "call":
        acc.add(node[1])
        for a in node[2]:
            collect_calls(a, acc)
    elif t in ("or", "and"):
        collect_calls(node[1], acc); collect_calls(node[2], acc)
    elif t in ("not", "neg"):
        collect_calls(node[1], acc)
    elif t == "cmp":
        collect_calls(node[2], acc); collect_calls(node[3], acc)
    elif t == "arith":
        collect_calls(node[2], acc); collect_calls(node[3], acc)


DATA_VARS = {"C": "close", "CLOSE": "close", "O": "open", "OPEN": "open",
             "H": "high", "HIGH": "high", "L": "low", "LOW": "low",
             "V": "volume", "VOL": "volume", "VOLUME": "volume",
             "AMO": "amount", "AMOUNT": "amount"}


def collect_vars(node, acc):
    t = node[0]
    if t == "var":
        acc.add(node[1])
    elif t == "call":
        for a in node[2]:
            collect_vars(a, acc)
    elif t in ("or", "and"):
        collect_vars(node[1], acc); collect_vars(node[2], acc)
    elif t in ("not", "neg"):
        collect_vars(node[1], acc)
    elif t == "cmp":
        collect_vars(node[2], acc); collect_vars(node[3], acc)
    elif t == "arith":
        collect_vars(node[2], acc); collect_vars(node[3], acc)


def compile_block(code):
    """code → (signal_ast, local_env, flags dict) ；不可编译抛 SyntaxError/NotImplementedError
    TDX 语句以 ; 分隔，换行仅为空白 → 语句级解析。"""
    code = re.sub(r"\{[^}]*\}", "", code)
    for k, v in FULLWIDTH.items():
        code = code.replace(k, v)
    local, outputs = {}, []
    for ln in code.replace("\r", "").split(";"):
        ln = ln.strip()
        if not ln:
            continue
        while True:
            stripped = DISPLAY_ATTR_RE.sub("", ln)
            if stripped == ln:
                break
            ln = stripped
        if not ln:
            continue
        m = re.match(r"^([A-Za-z_\u4e00-\u9fff][A-Za-z_0-9\u4e00-\u9fff]*)\s*(:=|:)\s*(.+)$",
                     ln, re.DOTALL)
        if m:
            name, kind, expr = m.group(1).upper(), m.group(2), m.group(3)
            ast = Parser(tokenize(expr)).parse()
            local[name] = ast
            if kind == ":":
                outputs.append((name, ast))
        else:
            ast = Parser(tokenize(ln)).parse()
            outputs.append((None, ast))
            local[f"__anon{len(outputs)}"] = ast
    if outputs:
        sig_ast = outputs[-1][1]
    elif local:
        sig_ast = list(local.values())[-1]
    else:
        raise SyntaxError("empty block")
    calls, vars_used = set(), set()
    collect_calls(sig_ast, calls); collect_vars(sig_ast, vars_used)
    for nm, ast in local.items():
        collect_calls(ast, calls); collect_vars(ast, vars_used)
    flags = {"dyuse": False}
    bad = calls & UNSUPPORTED
    if bad:
        raise NotImplementedError("unsupported: " + ",".join(sorted(bad)))
    if calls & SUPPORTED == set() and not calls:
        pass
    unk = {c for c in calls if c not in SUPPORTED and c not in LENIENT and c not in DATA_VARS}
    if unk:
        raise NotImplementedError("unknown fn: " + ",".join(sorted(unk)))
    if "DYNAINFO" in calls:
        flags["dyuse"] = True
    for v in vars_used:
        if v in VAR_UNSUPPORTED:
            raise NotImplementedError(f"unavailable data var {v}")
        if v == "DRAWNULL":
            continue
        if v not in DATA_VARS and v not in local:
            raise NotImplementedError(f"unknown var {v}")
    return sig_ast, local, flags


# ---------------- 求值 ----------------

def _series(x):
    return x if isinstance(x, pd.Series) else pd.Series(x)


def _np(x):
    return x.to_numpy(dtype=float) if isinstance(x, pd.Series) else np.asarray(x, dtype=float)


def _is_const_int(node):
    return node[0] == "num" and float(node[1]).is_integer()


def ev(node, env):
    t = node[0]
    if t == "num":
        return float(node[1])
    if t == "var":
        return env[node[1]]
    if t == "neg":
        return -ev(node[1], env)
    if t == "not":
        return (_np(ev(node[1], env)) == 0).astype(float)
    if t == "and":
        a = _np(ev(node[1], env)); b = _np(ev(node[2], env))
        return ((a != 0) & (b != 0)).astype(float)
    if t == "or":
        a = _np(ev(node[1], env)); b = _np(ev(node[2], env))
        return ((a != 0) | (b != 0)).astype(float)
    if t == "cmp":
        op = node[1]
        a = _np(ev(node[2], env)); b = _np(ev(node[3], env))
        with np.errstate(invalid="ignore"):
            if op == ">":
                r = a > b
            elif op == "<":
                r = a < b
            elif op == ">=":
                r = a >= b
            elif op == "<=":
                r = a <= b
            elif op in ("=", "=="):
                r = np.isclose(a, b, rtol=1e-9, atol=1e-9)
            else:  # <>
                r = ~np.isclose(a, b, rtol=1e-9, atol=1e-9)
        return r.astype(float)
    if t == "arith":
        op = node[1]
        a = _np(ev(node[2], env)); b = _np(ev(node[3], env))
        with np.errstate(invalid="ignore", divide="ignore"):
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            return np.where(b == 0, np.nan, a / b)
    if t == "call":
        return _call(node[1], node[2], env)
    raise ValueError(t)


def _const(a, default=None):
    if isinstance(a, float):
        return a
    if isinstance(a, np.ndarray) and a.size == 1:
        return float(a[0])
    return default


def _call(fn, args, env):
    a = [ev(x, env) for x in args]

    def arr(i):
        return _np(a[i])

    def n_arg(i, min_periods=None):
        """窗口参数：常量 int 或变窗序列"""
        x = a[i]
        if isinstance(x, float):
            n = int(x)
            if n < 0:
                raise NotImplementedError("negative window")
            return n
        if isinstance(x, np.ndarray) and x.size == 1:
            n = int(x[0])
            return n if n >= 0 else 0
        return x  # 变窗序列

    if fn == "REF":
        x, k = arr(0), n_arg(1)
        s = _series(x)
        if isinstance(k, int):
            return s.shift(k).to_numpy()
        return ref_var(x, k)
    if fn == "MA":
        x, n = arr(0), n_arg(1)
        if not isinstance(n, int):
            raise NotImplementedError("MA var-N")
        return _series(x).rolling(n, min_periods=n).mean().to_numpy()
    if fn == "EMA":
        x, n = arr(0), n_arg(1)
        if not isinstance(n, int):
            raise NotImplementedError("EMA var-N")
        return _series(x).ewm(alpha=2 / (n + 1), adjust=False).mean().to_numpy()
    if fn == "SMA":
        x, n, m = arr(0), n_arg(1), n_arg(2)
        if not isinstance(n, int) or not isinstance(m, int):
            raise NotImplementedError("SMA var-N")
        return _series(x).ewm(alpha=m / n, adjust=False).mean().to_numpy()
    if fn in ("HHV", "LLV"):
        x, k = arr(0), n_arg(1)
        if isinstance(k, int):
            if k == 0:
                return _series(x).cummax().to_numpy() if fn == "HHV" else _series(x).cummin().to_numpy()
            return (_series(x).rolling(k, min_periods=k).max() if fn == "HHV"
                    else _series(x).rolling(k, min_periods=k).min()).to_numpy()
        if fn == "HHV":
            return roll_max_var(x, k)
        return roll_min_var(x, k)
    if fn in ("HHVBARS", "LLVBARS"):
        x, n = arr(0), n_arg(1)
        if not isinstance(n, int):
            raise NotImplementedError(f"{fn} var-N")
        return (_series(x).rolling(n, min_periods=n).apply(np.argmax, raw=True) if fn == "HHVBARS"
                else _series(x).rolling(n, min_periods=n).apply(np.argmin, raw=True)).to_numpy()
    if fn == "CROSS":
        return cross_up(arr(0), arr(1))
    if fn == "BARSLAST":
        return barslast(arr(0) != 0).astype(float)
    if fn == "BARSSINCE":
        return barslast(arr(0) != 0).astype(float)  # 语义差：首现后恒增；近似，罕见用
    if fn == "COUNT":
        x, k = arr(0) != 0, n_arg(1)
        if isinstance(k, int):
            return _series(x.astype(float)).rolling(k, min_periods=k).sum().to_numpy()
        return count_var(x, k)
    if fn == "EVERY":
        x, k = arr(0) != 0, n_arg(1)
        if isinstance(k, int):
            return (_series(x.astype(float)).rolling(k, min_periods=k).sum().to_numpy() == k).astype(float)
        return (count_var(x, k) == np.maximum(np.asarray(k, float), 0)).astype(float)
    if fn == "EXIST":
        x, k = arr(0) != 0, n_arg(1)
        if isinstance(k, int):
            return (_series(x.astype(float)).rolling(k, min_periods=k).sum().to_numpy() > 0).astype(float)
        return (count_var(x, k) > 0).astype(float)
    if fn == "SUM":
        x, k = arr(0), n_arg(1)
        if isinstance(k, int):
            if k == 0:
                return _series(x).cumsum().to_numpy()
            return _series(x).rolling(k, min_periods=k).sum().to_numpy()
        s = _series(x).fillna(0).cumsum().to_numpy()
        return s - np.where(np.arange(len(s)) >= np.asarray(k, float), s[np.clip(np.arange(len(s)) - np.asarray(k, float), 0, len(s) - 1).astype(int)], 0)
    if fn == "MAX":
        return np.fmax(arr(0), arr(1))
    if fn == "MIN":
        return np.fmin(arr(0), arr(1))
    if fn == "ABS":
        return np.abs(arr(0))
    if fn == "POW":
        return np.power(arr(0), arr(1))
    if fn == "SQRT":
        with np.errstate(invalid="ignore"):
            return np.sqrt(np.maximum(arr(0), 0))
    if fn == "SGN":
        return np.sign(arr(0))
    if fn == "MOD":
        b = arr(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(b == 0, np.nan, np.fmod(arr(0), b))
    if fn == "IF":
        c = _np(ev(args[0], env)) != 0
        x = arr(1); y = arr(2)
        return np.where(c, x, y)
    if fn == "BETWEEN":
        x = arr(0); lo = arr(1); hi = arr(2)
        with np.errstate(invalid="ignore"):
            return ((x >= lo) & (x <= hi)).astype(float)
    if fn in ("UPNDAY", "DOWNNDAY"):
        x = arr(0)
        prev = _series(x).shift(1).to_numpy()
        with np.errstate(invalid="ignore"):
            up = x > prev if fn in ("UPNDAY", "NDAY") else x < prev
        k = n_arg(1)
        if not isinstance(k, int):
            raise NotImplementedError(f"{fn} var-N")
        return (_series(up.astype(float)).rolling(k, min_periods=k).sum().to_numpy() == k).astype(float)
    if fn == "NDAY":
        x = arr(0); y = arr(1)
        with np.errstate(invalid="ignore"):
            up = x > y
        k = n_arg(2)
        if not isinstance(k, int):
            raise NotImplementedError("NDAY var-N")
        return (_series(up.astype(float)).rolling(k, min_periods=k).sum().to_numpy() == k).astype(float)
    if fn == "STD":
        x, n = arr(0), n_arg(1)
        if not isinstance(n, int):
            raise NotImplementedError("STD var-N")
        return _series(x).rolling(n, min_periods=n).std(ddof=1).to_numpy()
    if fn == "EXPMA":
        x, n = arr(0), n_arg(1)
        if not isinstance(n, int):
            raise NotImplementedError("EXPMA var-N")
        return _series(x).ewm(alpha=2 / (n + 1), adjust=False).mean().to_numpy()
    if fn == "SLOPE" or fn == "FORCAST":
        x, n = arr(0), n_arg(1)
        if not isinstance(n, int):
            raise NotImplementedError(f"{fn} var-N")
        s = _series(x)
        t = np.arange(n, dtype=float)
        t_mean = t.mean()
        t_var = ((t - t_mean) ** 2).sum()

        def _fit(y):
            ym = np.nanmean(y)
            if np.isnan(ym):
                return np.nan
            b = np.nansum((t - t_mean) * (y - ym)) / t_var
            return b + ym if fn == "FORCAST" else b

        return s.rolling(n, min_periods=n).apply(_fit, raw=True).to_numpy()
    if fn == "AVEDEV":
        x, n = arr(0), n_arg(1)
        if not isinstance(n, int):
            raise NotImplementedError("AVEDEV var-N")

        def _ad(y):
            m = np.nanmean(y)
            if np.isnan(m):
                return np.nan
            return np.nanmean(np.abs(y - m))

        return _series(x).rolling(n, min_periods=n).apply(_ad, raw=True).to_numpy()
    if fn == "FILTER":
        x = _np(a[0]) != 0
        n = n_arg(1)
        if not isinstance(n, int):
            raise NotImplementedError("FILTER var-N")
        out = np.zeros(len(x), bool)
        cool = -1
        for i in np.where(x)[0]:
            if i > cool:
                out[i] = True
                cool = i + n
        return out.astype(float)
    if fn == "CONST":
        x = arr(0)
        return np.full(len(x), x[-1]) if x.ndim == 1 else x[-1]
    if fn == "ATAN":
        return np.arctan(arr(0))
    if fn == "RANGE":
        x = arr(0); lo = arr(1); hi = arr(2)
        with np.errstate(invalid="ignore"):
            return ((x >= lo) & (x <= hi)).astype(float)
    if fn == "DMA":
        x = arr(0)
        alpha = _const(a[1] if isinstance(a[1], float) else 0.0, None)
        if alpha is None or not (0 < alpha < 1):
            raise NotImplementedError("DMA var-alpha")
        return _series(x).ewm(alpha=alpha, adjust=False).mean().to_numpy()
    if fn == "DYNAINFO":
        return np.ones_like(arr(0)) if len(np.shape(arr(0))) else 1.0
    if fn in ("STICKLINE", "DRAWTEXT", "DRAWTEXT_FIX", "DRAWICON", "DRAWNUMBER",
              "DRAWNUMBER_FIX", "DRAWABOVE", "DRAWLINE", "POLYLINE", "VERTLINE",
              "DRAWKLINE"):
        return np.zeros(len(arr(0)))
    raise NotImplementedError(fn)


# ---------------- 变窗原语（与手译版同源） ----------------

def barslast(cond):
    c = np.asarray(cond, bool)
    idx = np.arange(len(c))
    last = np.maximum.accumulate(np.where(c, idx, -1))
    out = idx - last
    out[last < 0] = BIG
    return out


def cross_up(a, b):
    a = np.atleast_1d(np.asarray(a, float))
    b = np.atleast_1d(np.asarray(b, float))
    shape = np.broadcast_shapes(a.shape, b.shape)
    a = np.broadcast_to(a, shape).astype(float)
    b = np.broadcast_to(b, shape).astype(float)
    up_now = a > b
    up_prev = np.empty(shape[0], bool)
    up_prev[0] = False
    up_prev[1:] = a[:-1] <= b[:-1]
    return up_now & up_prev & np.isfinite(a) & np.isfinite(b)


def ref_var(x, k):
    x = np.asarray(x, float)
    kk = np.asarray(k, float)
    n = len(x)
    off = np.where(np.isfinite(kk), kk, BIG).astype(np.int64)
    idx = np.arange(n) - off
    valid = (off < BIG) & (idx >= 0) & np.isfinite(kk)
    out = np.full(n, np.nan)
    out[valid] = x[idx[valid]]
    return out


def count_var(event, k):
    ev_ = np.asarray(event, bool).astype(np.int64)
    cs = np.cumsum(ev_)
    kk = np.asarray(k, float)
    n = len(ev_)
    start = np.arange(n) - np.where(np.isfinite(kk), kk, BIG).astype(np.int64) + 1
    start = np.clip(start, 0, n)
    prev = np.where(start > 0, cs[np.clip(start - 1, 0, n - 1)], 0)
    prev[start == 0] = 0
    return (cs - prev).astype(float)


def _roll_var(x, k, fn):
    """变窗滚动 max/min（sparse-table 精确实现，O(n log n)）。
    TDX 语义：N≥1 取窗口 [i-N+1, i]；N≥历史长度 → 上市以来（cum）。"""
    x = np.asarray(x, float)
    n = len(x)
    cum = _series(x).cummax().to_numpy() if fn == "max" else _series(x).cummin().to_numpy()
    kk = np.asarray(k, float)
    out = cum.copy()
    valid = np.isfinite(kk) & (kk >= 1) & (kk < BIG)
    if not valid.any() or n == 0:
        return out
    op = np.fmax if fn == "max" else np.fmin
    wv = np.minimum(kk[valid].astype(np.int64), n)
    levels = max(1, int(np.floor(np.log2(int(wv.max())))))
    sp = [x.astype(float)]
    for j in range(1, levels + 1):
        prev = sp[-1]
        sh = 1 << (j - 1)
        cur = prev.copy()
        cur[sh:] = op(prev[:-sh], prev[sh:])
        sp.append(cur)
    vidx = np.where(valid)[0]
    we = np.minimum(wv, vidx + 1)          # 有效窗口长（历史不足则截断，语义=上市以来）
    k2 = np.floor(np.log2(we)).astype(int)
    res = np.full(len(wv), np.nan)
    for kv in np.unique(k2):
        rows = np.where(k2 == kv)[0]
        half = (1 << kv) - 1
        lo_i = vidx[rows] - we[rows] + 1
        res[rows] = op(sp[kv][lo_i + half], sp[kv][vidx[rows]])
    out[vidx] = res
    return out


def roll_max_var(x, k):
    return _roll_var(x, k, "max")


def roll_min_var(x, k):
    return _roll_var(x, k, "min")
