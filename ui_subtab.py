# -*- coding: utf8 -*-
"""看板子标签组件（R-dash-subtab-0922）

需求（用户 2026-09-22）：做成 i.gushi.in 式「大类 → 策略子标签」结构，全部策略通用。
设计：复用既有 .view 的 show/hide 模式，加一层 .subview；不改各卡片内部（只在组合期包裹）。

陷阱规避（项目已知 5 类模板坑）：
  ① CSS 用 /* */ 注释，禁 #
  ② 本文件为**普通字符串**（非 f-string），故无需双写花括号 —— 这是把它单独成文件的原因
  ③ 不写进 ui_components.THEME_CSS（共享模块），只在 build_dual_system 的 <style> 里追加
"""
import html as _html


SUBNAV_CSS = """
/* ===== 策略子标签（R-dash-subtab-0922）===== */
.subnav{display:flex;gap:8px;overflow-x:auto;padding:2px 0 10px;margin:0 0 4px;
  border-bottom:1px solid var(--border);scrollbar-width:thin}
.subnav::-webkit-scrollbar{height:6px}
.subnav::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.subtab{flex:0 0 auto;display:inline-flex;align-items:center;gap:7px;padding:7px 13px;
  border:1px solid var(--border);background:var(--card2);color:var(--sub);
  border-radius:var(--r);font-size:13px;line-height:1.3;cursor:pointer;white-space:nowrap;
  transition:background .12s,color .12s,border-color .12s}
.subtab:hover{color:var(--text);border-color:var(--accent)}
.subtab.on{background:var(--accent);color:#fff;border-color:var(--accent);font-weight:600}
.subtab .subn{font-size:11px;color:var(--faint);background:var(--card);border:1px solid var(--border);
  border-radius:var(--r-sm);padding:0 5px;min-width:18px;text-align:center}
.subtab.on .subn{color:#fff;background:rgba(255,255,255,.22);border-color:transparent}
.subtab .zfw{font-size:10px;color:var(--faint);border:1px solid var(--border);
  border-radius:var(--r-sm);padding:0 4px}
.subtab.on .zfw{color:#fff;border-color:rgba(255,255,255,.4)}
.subview{display:none}
.subview.active{display:block}
.subview > .pool-sec:first-child{margin-top:2px}
/* 子标签自有回测块（R-btshort-param-0924）：默认隐藏，由 SUBNAV_JS 按 data-sub 打开 */
.bt-sub{display:none}
.bt-sub.on{display:block}
.subhint{font-size:11.5px;color:var(--faint);margin:6px 2px 12px;line-height:1.7}
"""


SUBNAV_JS = r"""
/* ===== 策略子标签切换（R-dash-subtab-0922）=====
   与既有 switchView 同一模式：只切 class，不重载页面。
   锚点：一级 #<view>（既有），二级 ##<sub> 用 '#sub-<key>' 记录。 */
(function () {
  function activate(bar, key, push) {
    var view = bar.closest('.view');
    if (!view) return;
    var ok = false;
    view.querySelectorAll('.subview').forEach(function (sv) {
      var hit = (sv.id === 'sv-' + key);
      sv.classList.toggle('active', hit);
      if (hit) ok = true;
    });
    /* 子标签自有「回测数据」块：与 .subview 同一把 key，控制 [data-bt-sub] 的显隐
       （R-btshort-param-0924：消掉 #bt-short 被多子标签共用） */
    view.querySelectorAll('[data-bt-sub]').forEach(function (bs) {
      var k2 = bs.getAttribute('data-bt-sub');
      if (k2) bs.classList.toggle('on', k2 === key);
    });
    if (!ok) return false;
    bar.querySelectorAll('.subtab').forEach(function (b) {
      b.classList.toggle('on', b.getAttribute('data-sub') === key);
    });
    bar.setAttribute('data-cur', key);
    if (push) {
      var vid = view.id.replace(/^view-/, '');
      try { history.replaceState(null, '', '#' + vid + '/sub-' + key); } catch (e) {}
    }
    return true;
  }

  function initBar(bar) {
    if (bar.getAttribute('data-init') === '1') return;
    bar.setAttribute('data-init', '1');
    var view = bar.closest('.view');
    var want = null;
    var h = (location.hash || '').replace(/^#/, '');
    if (h && h.indexOf('/sub-') >= 0) {
      want = h.split('/sub-')[1];
    }
    if (!want) {
      /* 服务端可用 .subtab.on 指定默认子标签；否则取第一个 */
      var dflt = bar.querySelector('.subtab.on') || bar.querySelector('.subtab');
      want = dflt ? dflt.getAttribute('data-sub') : null;
    }
    if (want) activate(bar, want, false);
    bar.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('.subtab') : null;
      if (!b || !bar.contains(b)) return;
      activate(bar, b.getAttribute('data-sub'), true);
    });
  }

  function initAll() {
    document.querySelectorAll('.subnav').forEach(initBar);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
  window.SUBTAB_INIT = initAll;
  /* 视图切换后确保子标签已初始化（其它脚本可能后插入内容） */
  window.addEventListener('hashchange', initAll);
})();
"""


def subnav(view_key, items, default_key=None):
    """子标签横条。

    items = [(sub_key, 标题, 计数或None, 是否零资金对照)]
    default_key: 默认激活的子标签；None 则取第一个。与 HTML 中的 subview 顺序无关。
    """
    out = ['<div class="subnav" data-view="%s" data-default="%s">'
           % (_html.escape(str(view_key), quote=True), _html.escape(str(default_key or ""), quote=True))]
    for it in items:
        k, title = it[0], it[1]
        n = it[2] if len(it) > 2 else None
        zfw = it[3] if len(it) > 3 else False
        _on = " on" if (default_key is not None and k == default_key) else ""
        out.append('<button class="subtab%s" data-sub="%s" type="button">%s'
                   % (_on, _html.escape(str(k), quote=True), _html.escape(str(title))))
        if zfw:
            out.append('<span class="zfw">对照·零资金</span>')
        if n is not None:
            out.append('<span class="subn">%s</span>' % _html.escape(str(n)))
        out.append('</button>')
    out.append('</div>')
    return "".join(out)


def subview(sub_key, title, subtitle, body_html):
    """一个策略面板：节标题 + 内容。body_html 原样透传（已是 HTML）。"""
    return ('<div class="subview" id="sv-%s">\n'
            '<div class="pool-sec"><b>%s</b><span>%s</span></div>\n%s\n</div>\n'
            % (_html.escape(str(sub_key), quote=True), _html.escape(str(title)),
               _html.escape(str(subtitle)), body_html))


ASSET_HINT = ('<div class="subhint">⚖ 资产配置由用户决定：本页所有「权重 / 计划金额 / 目标权重」'
              '均为<b>策略输出</b>或<b>等权参考</b>，不构成仓位建议。</div>')
