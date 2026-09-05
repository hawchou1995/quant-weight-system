/* 2026-09-05 渲染验证 v2：KHunter 命中策略一览卡（短线视图）
   覆盖用户三项反馈：①表头存在 ②分域无问号 ③标准/激进四列独立 */
const { chromium } = require('playwright-core');
const path = require('path');

(async () => {
  const exe = 'C:/Users/Admin/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe';
  const browser = await chromium.launch({ executablePath: exe, headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));

  const url = 'file:///' + path.resolve(__dirname, 'dual_system.html').replace(/\\/g, '/');
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2500);

  // 切到短线视图
  await page.evaluate(() => switchView('short'));
  await page.waitForTimeout(800);

  // 0. 表头校验（用户反馈①：表格没有表头）
  const headers = await page.$$eval('#kh-hits-table thead th', ths => ths.map(th => th.textContent.trim()));
  console.log('表头列数:', headers.length, '(期望 16)');
  console.log('表头:', JSON.stringify(headers));
  const hOk = headers.length === 16
    && headers.includes('档位(标准)') && headers.includes('建议(标准)')
    && headers.includes('档位(激进)') && headers.includes('建议(激进)');
  console.log('表头校验:', hOk ? '✅' : '❌');

  // 1. 命中表行数 + 16 列结构
  const rows = await page.$$eval('#kh-hits-table tbody tr', trs => trs.map(tr => {
    const tds = tr.querySelectorAll('td');
    return {
      n: tds[0] ? tds[0].textContent.trim() : '',
      code: tds[1] ? tds[1].textContent.trim() : '',
      name: tds[2] ? tds[2].textContent.trim() : '',
      board: tds[3] ? tds[3].textContent.trim() : '',
      perm: tds[4] ? tds[4].textContent.trim() : '',
      ind: tds[5] ? tds[5].textContent.trim() : '',
      rsi: tds[8] ? tds[8].textContent.trim() : '',
      regime: tds[10] ? tds[10].textContent.trim() : '',
      strat: tds[11] ? tds[11].textContent.trim() : '',
      stTier: tds[12] ? tds[12].textContent.trim() : '',
      stAct: tds[13] ? tds[13].textContent.trim() : '',
      agTier: tds[14] ? tds[14].textContent.trim() : '',
      agAct: tds[15] ? tds[15].textContent.trim() : '',
    };
  }));
  console.log('命中表行数:', rows.length);
  const badCols = rows.filter(r => !r.stTier || !r.stAct || !r.agTier || !r.agAct).length;
  console.log('四列缺失行:', badCols, '/', rows.length, badCols === 0 ? '✅' : '❌');
  console.log('前 3 行:', JSON.stringify(rows.slice(0, 3), null, 1));
  console.log('末 1 行:', JSON.stringify(rows[rows.length - 1], null, 1));

  // 2. RSI 升序校验
  const rsis = rows.map(r => parseFloat(r.rsi));
  let asc = true;
  for (let i = 1; i < rsis.length; i++) if (rsis[i] < rsis[i - 1]) { asc = false; break; }
  console.log('RSI 升序:', asc ? '✅' : '❌', rsis.slice(0, 5), '...', rsis.slice(-3));

  // 3. 分域校验（用户反馈②：市场状态一堆问号）
  const regs = {};
  rows.forEach(r => regs[r.regime] = (regs[r.regime] || 0) + 1);
  console.log('分域分布:', JSON.stringify(regs));
  const qMarks = rows.filter(r => r.regime === '?' || r.regime === '—').length;
  console.log('分域问号/缺失:', qMarks, '/', rows.length, qMarks === 0 ? '✅' : '❌');

  // 4. 标准/激进四列独立校验（用户反馈③：档位/建议打架）
  const stTiers = {}, agTiers = {};
  rows.forEach(r => { stTiers[r.stTier] = (stTiers[r.stTier] || 0) + 1; agTiers[r.agTier] = (agTiers[r.agTier] || 0) + 1; });
  console.log('标准版档位分布:', JSON.stringify(stTiers));
  console.log('激进版档位分布:', JSON.stringify(agTiers));
  // 标准版卖出行，其建议列必须含「卖出」字样；激进版同理
  const stSellBad = rows.filter(r => r.stTier === '卖出' && r.stAct.indexOf('卖出') < 0).length;
  const agSellBad = rows.filter(r => r.agTier === '卖出' && r.agAct.indexOf('卖出') < 0).length;
  console.log('标准卖出建议列异常:', stSellBad, '| 激进卖出建议列异常:', agSellBad, (stSellBad + agSellBad) === 0 ? '✅' : '❌');
  // 同一行标准/激进可同时为卖出（不打架 = 各自独立展示）
  const bothSell = rows.filter(r => r.stTier === '卖出' && r.agTier === '卖出').length;
  console.log('标准+激进同时卖出行数:', bothSell, '(独立展示，互不覆盖)');

  // 5. 行业缺失
  const noInd = rows.filter(r => r.ind === '—' || !r.ind).length;
  console.log('行业缺失:', noInd, '/', rows.length);

  // 6. 计数徽章
  const cnt = await page.$eval('#kh-hits-count', el => el.textContent);
  console.log('计数徽章:', cnt);

  // 7. 筛选测试：档位=卖出（按标准版）
  await page.selectOption('#kh-hits-f-tier', '卖出');
  await page.waitForTimeout(300);
  const sellRows = await page.$$eval('#kh-hits-table tbody tr', trs => trs.length);
  console.log('筛选[标准=卖出] 行数:', sellRows, '(期望', stTiers['卖出'] || 0, ')', sellRows === (stTiers['卖出'] || 0) ? '✅' : '❌');

  // 8. 搜索测试
  await page.fill('#kh-hits-q', '金杯');
  await page.waitForTimeout(300);
  const qRows = await page.$$eval('#kh-hits-table tbody tr', trs => trs.length);
  console.log('搜索[金杯] 行数:', qRows, '(期望 1)');

  // 9. 跟踪池行业列（回归）
  await page.fill('#kh-hits-q', '');
  await page.selectOption('#kh-hits-f-tier', '');
  await page.waitForTimeout(300);
  const watchRows = await page.$$eval('#watch-table tbody tr', trs => trs.map(tr => {
    const tds = tr.querySelectorAll('td');
    return { code: tds[0] ? tds[0].textContent.trim() : '', ind: tds[4] ? tds[4].textContent.trim() : '' };
  }));
  const watchNoInd = watchRows.filter(r => r.ind === '—' || !r.ind).length;
  console.log('跟踪池行数:', watchRows.length, '| 行业缺失:', watchNoInd, '/', watchRows.length);

  console.log('JS 错误:', errors.length ? errors.slice(0, 5) : '无 ✅');
  await browser.close();
})().catch(e => { console.error('❌ 验证失败:', e.message); process.exit(1); });
