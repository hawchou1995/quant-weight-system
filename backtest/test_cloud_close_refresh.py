"""Regression contracts for the cloud closing data pipeline (no production writes)."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TX = load("closing_tx", "backtest/em_tencent_fill.py")
INDEX = load("closing_index", "backtest/ensure_index_row.py")
CLOUD = load("closing_cloud", ".github/cloud/cloud_refresh.py")
BREADTH = load("closing_breadth", "build_market_breadth.py")
DAY = "2026-10-13"


class BatchDateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.data = self.base / "data_full"
        self.data.mkdir()
        self.cal = self.base / "index.csv"
        self.cal.write_text("date,open,high,low,close,volume\n2026-10-12,10,11,9,10,100\n", encoding="utf-8")
        self.csv = self.data / "sz000001.csv"
        self.csv.write_text("date,open,high,low,close,volume,amount\n2026-10-12,10,11,9,10,100,1000\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_batch(self, timestamp, extra=()):
        quote = (timestamp, 10.0, 11.0, 9.0, 10.5, 100.0, 1050.0)
        with mock.patch.object(TX, "DATA", str(self.data)), mock.patch.object(TX, "CAL", str(self.cal)), \
             mock.patch.object(TX, "DI", None), mock.patch.object(TX, "fetch_tx", return_value={"000001": quote}), \
             mock.patch.object(sys, "argv", ["tx", "--date", DAY, *extra]), contextlib.redirect_stdout(io.StringIO()):
            return TX.main()

    def test_explicit_data_date_ignores_stale_index(self):
        self.assertEqual(self.run_batch("20261013150000"), 0)
        self.assertIn("2026-10-13,", self.csv.read_text(encoding="utf-8"))
        self.assertEqual(TX.trade_day(DAY), DAY)

    def test_intraday_and_stale_quotes_never_write(self):
        original = self.csv.read_bytes()
        for timestamp in ("20261013145959", "20261012161500", "20261014161500", "2026101315"):
            self.run_batch(timestamp)
            self.assertEqual(original, self.csv.read_bytes(), timestamp)

    def test_same_day_replay_is_byte_idempotent(self):
        self.run_batch("20261013150000")
        original = self.csv.read_bytes()
        self.run_batch("20261013161500")
        self.assertEqual(original, self.csv.read_bytes())
        self.assertEqual(self.csv.read_text(encoding="utf-8").count(DAY), 1)

    def test_dry_run_writes_nothing(self):
        original = self.csv.read_bytes()
        self.run_batch("20261013161500", ("--dry",))
        self.assertEqual(original, self.csv.read_bytes())

    def test_future_local_bar_is_not_overwritten(self):
        self.csv.write_text("date,open,high,low,close,volume,amount\n2026-10-14,10,11,9,10,100,1000\n", encoding="utf-8")
        original = self.csv.read_bytes()
        self.run_batch("20261013161500")
        self.assertEqual(original, self.csv.read_bytes())

    def test_bulk_caller_carries_probed_date(self):
        source = (ROOT / "update_daily.py").read_text(encoding="utf-8")
        self.assertIn('"--date", str(target_date)', source)


class IndexDateTests(unittest.TestCase):
    def test_midnight_target_is_actual_requested_bar_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "index.csv"
            p.write_text("date,open,high,low,close,volume\n2026-10-12,10,11,9,10,100\n", encoding="utf-8")
            bar = {"date": DAY, "open": 10, "high": 11, "low": 9, "close": 10.5, "vol_hand": 2}
            with mock.patch.dict(os.environ, {"QWS_TARGET_DATE": DAY}), \
                 mock.patch.object(sys, "argv", ["index", "--file", str(p)]), \
                 mock.patch.object(INDEX, "fetch_recent", return_value=({}, "")), \
                 mock.patch.object(INDEX, "fetch_em_bar", return_value=None), \
                 mock.patch.object(INDEX, "fetch_tx_bar", return_value=bar), \
                 mock.patch.object(INDEX, "fetch_sina_bar", return_value=None), \
                 contextlib.redirect_stdout(io.StringIO()):
                for _ in range(2):
                    with self.assertRaises(SystemExit) as ex:
                        INDEX.main()
                    self.assertEqual(ex.exception.code, 0)
            self.assertEqual(p.read_text(encoding="utf-8").count(DAY), 1)
            self.assertTrue(p.read_text(encoding="utf-8").rstrip().endswith("200"))


class CloudContractTests(unittest.TestCase):
    def test_legacy_cache_restore_and_save_layout_are_compatible(self):
        doc = yaml.safe_load((ROOT / ".github/workflows/close_refresh_cloud.yml").read_text(encoding="utf-8"))
        steps = doc["jobs"]["refresh"]["steps"]
        old = ["data_full", "data_hist", "fund_nav_cache", "data_fundamental", "backtest/a5_experiment"]
        restore = next(s for s in steps if s.get("id") == "cache")
        save = next(s for s in steps if s.get("name") == "保存数据缓存")
        self.assertEqual(restore["with"]["path"].split(), old)
        self.assertEqual(save["with"]["path"].split(), old)
        state_restore = next(s for s in steps if s.get("id") == "state_cache")
        self.assertNotIn("data_full", state_restore["with"]["path"])

    def test_new_production_data_are_hard_freshness_anchors(self):
        self.assertIn("a5_pool.js", CLOUD.G2_FILES)
        self.assertIn("market_breadth.js", CLOUD.G2_FILES)

    def test_breadth_generation_precedes_html_and_hpdk_is_visible(self):
        chain = (ROOT / "daily_refresh.py").read_text(encoding="utf-8")
        self.assertLess(chain.index('["build_market_breadth.py"'), chain.index('["build_dual_system.py"'))
        src = (ROOT / "build_dual_system.py").read_text(encoding="utf-8")
        view = src[src.index("SHORT_VIEW_HTML ="):src.index("def qlch_live_payload")]
        self.assertIn('("st-hpdk", "缩量超跌")', view)
        self.assertIn('subview("st-hpdk"', view)
        self.assertIn("hpdk_card() + hpdk_oos_card()", view)

    def test_timeout_stops_descendant_writes(self):
        with tempfile.TemporaryDirectory() as td:
            heartbeat = Path(td) / "heartbeat.txt"
            writer = "import time,sys; f=open(sys.argv[1],'a');\nwhile True: f.write('x'); f.flush(); time.sleep(.05)"
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); time.sleep(60)"
            with self.assertRaises(subprocess.TimeoutExpired):
                CLOUD.run_process_tree([sys.executable, "-c", parent, writer, str(heartbeat)], cwd=td, env=os.environ.copy(), timeout=2)
            self.assertTrue(heartbeat.exists())
            before = heartbeat.stat().st_size
            time.sleep(.4)
            self.assertEqual(before, heartbeat.stat().st_size)

    def test_midnight_expected_day_stays_latest_closed_session(self):
        from datetime import datetime, timezone, timedelta
        zone = timezone(timedelta(hours=8))
        self.assertEqual(CLOUD.latest_closed_weekday(datetime(2026, 10, 14, 1, tzinfo=zone)), DAY)
        self.assertEqual(CLOUD.latest_closed_weekday(datetime(2026, 10, 14, 15, tzinfo=zone)), "2026-10-14")

    def test_delayed_rt_job_does_not_roll_closing_files_back(self):
        guard = load("rt_guard", ".github/cloud/guard_rt_publish.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in guard.FILES:
                (root / name).write_bytes(b'{"as_of":"2026-10-12"}')
            output = root / "staging"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(guard.stage(root, output, lambda name: b'{"as_of":"2026-10-13"}'), [])
            self.assertEqual(list(output.iterdir()), [])
            for name in guard.FILES:
                (root / name).write_bytes(b'{"as_of":"2026-10-13"}')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(len(guard.stage(root, output, lambda name: b'{"as_of":"2026-10-13"}')), 3)

    def test_rt_publication_fails_closed_when_live_date_unverifiable(self):
        guard = load("rt_guard_failure", ".github/cloud/guard_rt_publish.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in guard.FILES:
                (root / name).write_bytes(b'{"as_of":"2026-10-13"}')
            with self.assertRaises(ValueError):
                guard.stage(root, root / "staging", lambda name: b'not dated')


    @unittest.skipIf(os.name == "nt", "POSIX process group contract exercised by cloud Linux runner")
    def test_normal_parent_exit_also_cleans_lingering_descendants(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "child.txt"
            writer = "import time,sys; f=open(sys.argv[1],'a');\nwhile True: f.write('x'); f.flush(); time.sleep(.05)"
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); time.sleep(.5)"
            self.assertEqual(CLOUD.run_process_tree([sys.executable, "-c", parent, writer, str(p)], cwd=td, env=os.environ.copy(), timeout=5), 0)
            before = p.stat().st_size
            time.sleep(.3)
            self.assertEqual(before, p.stat().st_size)


class ProductionViewTests(unittest.TestCase):
    def test_a5_projection_uses_real_date_prices_and_escapes_names(self):
        import ast
        src = (ROOT / "build_dual_system.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        names = {"asof_badge", "_a5_tbl_full", "a5_current_card"}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        scope = {"A5": {"as_of": DAY, "watchlist": [], "positions": [
            {"code": "sz000001", "name": "<unsafe>", "entry_date": DAY, "entry_px": 11.57}],
            "closed": [], "stats": {"nav": 0.76}}}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "projection", "exec"), scope)
        html = scope["a5_current_card"]()
        self.assertIn("数据截至 " + DAY, html)
        self.assertIn("11.57", html)
        self.assertIn("&lt;unsafe&gt;", html)
        self.assertNotIn("<unsafe>", html)
        self.assertIn('id="card-a5-current"', html)
        self.assertEqual(html.count("<div"), html.count("</div>"))

    def test_a5_tab_and_dropdown_are_wired(self):
        src = (ROOT / "build_dual_system.py").read_text(encoding="utf-8")
        view = src[src.index("SHORT_VIEW_HTML ="):src.index("def qlch_live_payload")]
        self.assertIn('("st-a5", "A5 实验盘")', view)
        self.assertIn('subview("st-a5"', view)
        self.assertIn('["card-a5-current","A5 实验盘"]', src)

    def test_closed_breadth_view_does_not_mix_stale_live_pools(self):
        program = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const part=source.slice(source.indexOf('function sentimentLevel('),source.indexOf('function renderIndices('));
const node={innerHTML:''};
const context={MB:{latest:{red:2790,green:2267,flat:167,limit_up:70,limit_down:10,broken_limit:22}},
 state:{breadth:{red:1,green:2,flat:3},pools:{limit_up:67,limit_down:8,broken_limit:19}},
 $:()=>node,isTrading:()=>false,fmtYi:String,fmtNum:String};
vm.runInNewContext(part+';renderSummary();',context);
assert(node.innerHTML.includes('2790'));assert(node.innerHTML.includes('2267'));
assert(node.innerHTML.includes('>70<'));assert(node.innerHTML.includes('>10<'));
console.log('CLOSED_BREADTH_RENDER_PASS');
'''
        result = subprocess.run(["node", "-e", program, str(ROOT / "market_weather.js")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLOSED_BREADTH_RENDER_PASS", result.stdout)


class BreadthDateTests(unittest.TestCase):
    def test_quote_day_not_wall_clock_day_is_published(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "breadth.js"
            summary = {"generated_at": DAY + " 16:15:00", "quote_count": 5000, "red": 2000, "green": 2900, "flat": 100}
            with mock.patch.object(BREADTH, "fetch_breadth_snapshot", return_value=summary), \
                 mock.patch.object(BREADTH, "compute_lianban", return_value={"lianban_max": 0, "lianban_count": 0, "lianban_top": []}):
                BREADTH.run_once(p, False, expect_as_of=DAY, close_only=True)
            payload = BREADTH.load_existing(p)
            self.assertEqual(payload["date"], DAY)
            self.assertEqual(payload["meta"]["as_of"], DAY)
            self.assertEqual(payload["latest"]["red"], 2000)

    def test_stale_or_empty_summary_never_relabels_old_prices(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "breadth.js"
            p.write_text("old", encoding="utf-8")
            for summary in ({"quote_count": 0}, {"quote_count": 5000, "generated_at": "2026-10-12 16:15:00"}):
                with mock.patch.object(BREADTH, "fetch_breadth_snapshot", return_value=summary):
                    with self.assertRaises(ValueError):
                        BREADTH.run_once(p, False, expect_as_of=DAY, close_only=True)
                self.assertEqual(p.read_text(encoding="utf-8"), "old")


if __name__ == "__main__":
    unittest.main()
