// 新浪日线快速拉取器（Node 原生 V8 解码，2026-09-08）
// =====================================================
// 背景：akshare 用 py_mini_racer 每次新建 JS VM 解码 klc_kl.js（1.79s/只，8线程仅~1只/s）。
// 本脚本：Node 24 内置 fetch + V8 原生执行 d() 解码（~1ms），32 并发纯异步。
// 流程：读滞后清单 → 并发拉 klc_kl.js + qfq.js → 解码 → 前复权 → 合并本地 → 原子写
// 用法：node em_fetch_node.js <lag_csv> <out_dir> [workers]
// 输出：每只一行进度到 stderr；退出码 0=全部成功
const fs = require('fs');
const path = require('path');

const hk_js_decode = fs.readFileSync(path.join(__dirname, 'hk_js_decode.js'), 'utf8');
eval(hk_js_decode); // 定义全局函数 d(t)

const UA = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' };
const DEBUG = process.env.EM_DEBUG === '1';
const HIST_URL = (s) => `https://finance.sina.com.cn/realstock/company/${s}/hisdata_klc2/klc_kl.js`;
const QFQ_URL = (s) => `https://finance.sina.com.cn/realstock/company/${s}/qfq.js`;

function parseCsvLine(line) {
  return line.split(',').map((x) => x.trim());
}

async function fetchOne(sym) {
  // 1. 原始行情（JS 加密）
  const r = await fetch(HIST_URL(sym), { headers: UA });
  if (!r.ok) { if (DEBUG) process.stderr.write(`  DBG ${sym} hist !ok ${r.status}\n`); return null; }
  const txt = await r.text();
  if (txt.length < 200) { if (DEBUG) process.stderr.write(`  DBG ${sym} hist short ${txt.length}\n`); return null; }
  const encoded = txt.split('=')[1].split(';')[0].replace(/"/g, '');
  const dictList = d(encoded);
  if (!Array.isArray(dictList) || dictList.length === 0) { if (DEBUG) process.stderr.write(`  DBG ${sym} decode empty\n`); return null; }

  // 2. 前复权因子（纯 JSON）
  const r2 = await fetch(QFQ_URL(sym), { headers: UA });
  if (!r2.ok) { if (DEBUG) process.stderr.write(`  DBG ${sym} qfq !ok ${r2.status}\n`); return null; }
  const txt2 = await r2.text();
  const facArr = JSON.parse(txt2.split('=')[1].split('\n')[0]).data;
  if (!Array.isArray(facArr) || facArr.length === 0) { if (DEBUG) process.stderr.write(`  DBG ${sym} fac empty\n`); return null; }
  const facMap = new Map(facArr.map((x) => [x.d, x.f]));

  // 3. 合并 + ffill + qfq = raw / factor
  // 3. 合并 + ffill + qfq = raw / factor
  // ⚠ 2026-09-08 三坑（血泪）：
  //  ① item.date 是 Date 对象！String(Date)="Tue Nov 10 1999..."，slice(0,10) 全错 → 必须用本地组件格式化
  //  ② akshare ffill 语义：初始因子=最老因子（facArr 降序最后一条=1900-01-01 兜底）
  //  ③ **lastFac 必须在日期过滤之前更新**！原写法先 continue 再更新 → 2016-01-04~06-22 段
  //     沿用 1900 兜底因子 17.39（应为 2.12）→ 前复权价差 8.2 倍 → v8 回测 -48.48%（已对 akshare 实证）
  const rows = [];
  let lastFac = facArr.length ? Number(facArr[facArr.length - 1].f) : 1;
  for (const item of dictList) {
    const dt = new Date(item.date);
    const date = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
    if (facMap.has(date)) lastFac = facMap.get(date);   // 先更新因子（含 2016 前的分红除权点）
    if (date < '2016-01-01') continue;                   // 再过滤输出范围
    const f = Number(lastFac);
    if (!f) continue;
    rows.push({
      date,
      open: Math.round((Number(item.open) / f) * 100) / 100,
      high: Math.round((Number(item.high) / f) * 100) / 100,
      low: Math.round((Number(item.low) / f) * 100) / 100,
      close: Math.round((Number(item.close) / f) * 100) / 100,
      volume: Number(item.volume),
      amount: Number(item.amount || 0),
    });
  }
  if (rows.length === 0) { if (DEBUG) process.stderr.write(`  DBG ${sym} rows empty (dictList=${dictList.length}, facMap=${facArr.length})\n`); }
  return rows;
}

function mergeAndSave(sym, rows, outDir) {
  const f = path.join(outDir, `${sym}.csv`);
  const seen = new Map();
  if (fs.existsSync(f)) {
    const lines = fs.readFileSync(f, 'utf8').split('\n');
    for (const line of lines) {
      if (!line.trim()) continue;
      if (line.startsWith('date,')) continue; // ⚠ 跳过表头（否则 "date" 排序在日期后，表头落文件尾）
      // ⚠ 旧 Python 数据行尾有 \r（CRLF）和尾逗号，必须清理并统一 7 列格式
      // （2026-09-08 血泪：不清理 → 混合换行文件 → pandas date 列读出 float）
      const p = line.replace(/\r$/, '').split(',');
      if (p.length >= 6) seen.set(p[0], p.slice(0, 7).join(','));
    }
  }
  for (const row of rows) {
    seen.set(row.date, `${row.date},${row.open},${row.high},${row.low},${row.close},${row.volume},${row.amount}`);
  }
  const sorted = [...seen.keys()].sort();
  const out = ['date,open,high,low,close,volume,amount', ...sorted.map((d) => seen.get(d))].join('\n') + '\n';
  const tmp = f + '.tmp';
  fs.writeFileSync(tmp, out, 'utf8');
  fs.renameSync(tmp, f);
  return sorted.length;
}

async function main() {
  const lagCsv = process.argv[2];
  const outDir = process.argv[3];
  const workers = parseInt(process.argv[4] || '32', 10);

  const lines = fs.readFileSync(lagCsv, 'utf8').split('\n').filter((l) => l.trim());
  const syms = lines.slice(1).map((l) => parseCsvLine(l)[0]).filter(Boolean);
  console.error(`Node 拉取器: ${syms.length} 只, ${workers} 并发`);

  let ok = 0, fail = 0, done = 0;
  const t0 = Date.now();
  const fails = [];

  async function worker(sym) {
    try {
      const rows = await fetchOne(sym);
      if (rows && rows.length > 0) {
        mergeAndSave(sym, rows, outDir);
        ok++;
      } else {
        fail++;
        fails.push(sym);
      }
    } catch (e) {
      fail++;
      fails.push(sym);
      if (done < 5) process.stderr.write(`  ERR ${sym}: ${e.message}\n`);
    }
    done++;
    if (done % 500 === 0 || done === syms.length) {
      const el = ((Date.now() - t0) / 1000).toFixed(0);
      process.stderr.write(`  [${done}/${syms.length}] 成功 ${ok} 失败 ${fail} 耗时 ${el}s\n`);
    }
  }

  // 简单并发池
  let idx = 0;
  async function pool() {
    while (idx < syms.length) {
      const sym = syms[idx++];
      await worker(sym);
    }
  }
  const poolers = [];
  for (let i = 0; i < workers; i++) poolers.push(pool());
  await Promise.all(poolers);

  const el = ((Date.now() - t0) / 1000).toFixed(0);
  process.stderr.write(`✅ Node 拉取完成: 成功 ${ok} / 失败 ${fail} / 总 ${syms.length}, 耗时 ${el}s\n`);
  if (fails.length) {
    fs.writeFileSync(path.join(outDir, '..', 'data_full_fail_list_node.csv'), fails.join('\n') + '\n', 'utf8');
    process.stderr.write(`失败清单: ${fails.slice(0, 10).join(', ')}...\n`);
  }
  process.exit(fail > 0 ? 1 : 0);
}

main();
