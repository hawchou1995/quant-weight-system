import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backtest"))
import sentinel_daily as S


class SentinelNameFilterTests(unittest.TestCase):
    def test_name_normalization_and_three_class_union(self):
        self.assertEqual(S.normalize_stock_name(" ＊ ST\u3000华鹏 "), "*ST华鹏")
        self.assertEqual(S.stock_name_exclusion_rules(" ST\u3000天际 "), {"plain_ST"})
        self.assertEqual(S.stock_name_exclusion_rules(" ＊ ST 华鹏 "), {"star_ST"})
        self.assertEqual(S.stock_name_exclusion_rules("国华 退"), {"delist_proxy"})
        self.assertEqual(S.stock_name_exclusion_rules("平安银行"), frozenset())

    def test_filter_runs_before_resonance_theta_and_pool_construction(self):
        codes = {
            "sh600000": "普通银行",
            "sz002759": " ST\u3000天际 ",
            "sh603021": "＊ ST 华鹏",
            "sz000004": "国华 退",
        }
        dates = pd.bdate_range("2016-06-01", periods=400)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            names_path = root / "data_full_names.json"
            names_path.write_text(json.dumps(codes, ensure_ascii=False), encoding="utf-8")
            index_path = root / "index.csv"
            pd.DataFrame({"date": dates.astype(str), "close": np.full(len(dates), 10.0)}).to_csv(index_path, index=False)
            data_dir = root / "data_full"
            data_dir.mkdir()
            frame = pd.DataFrame({
                "date": dates.astype(str),
                "open": np.full(len(dates), 10.0),
                "close": np.full(len(dates), 10.0),
                "amount": np.full(len(dates), 1_000_000.0),
                "volume": np.full(len(dates), 100_000.0),
            })
            for code in codes:
                frame.to_csv(data_dir / (code + ".csv"), index=False)

            yes = np.ones(len(dates), dtype=bool)
            no = np.zeros(len(dates), dtype=bool)
            signals = {key: (yes if key in ("rushi", "jiandi") else no) for key, _ in S.SUBS}
            messages = []
            with mock.patch.object(S, "IDX_CSV", index_path), \
                 mock.patch.object(S, "NAMES_JSON", names_path), \
                 mock.patch.object(S.JG, "jiandi_signals", return_value=signals):
                scan = S.do_scan(data_dir, pd.Timestamp(dates[-1]), messages.append, names=codes)
                last_day = scan["last_cal"]
                latest_pool = S.pool_entries(scan, last_day, codes)
                trigger_days = S.trigger_dates(scan["res_daily"], threshold=2)

            self.assertEqual(set(scan["cache"]), {"sh600000"})
            self.assertEqual(scan["name_filter_stats"]["excluded_union"], 3)
            self.assertEqual(scan["name_filter_stats"]["excluded_by_rule"], {
                "plain_ST": 1, "star_ST": 1, "delist_proxy": 1,
            })
            self.assertEqual(scan["res_daily"][last_day], 1)
            self.assertEqual(trigger_days, [])
            self.assertEqual([row["code"] for row in latest_pool], ["sh600000"])
            self.assertNotIn("ST", " ".join(row["name"] for row in latest_pool))
            self.assertTrue(any("过滤先于信号计算" in message for message in messages))
            meta = S.name_filter_payload(scan)
            self.assertFalse(meta["point_in_time"])
            self.assertTrue(meta["applied_before_signal_count"])
            self.assertEqual(meta["source_snapshot_as_of"], "2026-08-17")

    def test_unclassified_eligible_stock_aborts_before_signal_calls(self):
        dates = pd.bdate_range("2016-06-01", periods=400)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            names_path = root / "data_full_names.json"
            names = {"sh600999": "名称样本以外"}
            names_path.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
            index_path = root / "index.csv"
            pd.DataFrame({"date": dates.astype(str), "close": np.full(len(dates), 10.0)}).to_csv(index_path, index=False)
            data_dir = root / "data_full"
            data_dir.mkdir()
            pd.DataFrame({"date": dates.astype(str), "open": 10.0, "close": 10.0,
                          "amount": 1_000_000.0, "volume": 100_000.0}).to_csv(
                              data_dir / "sh600000.csv", index=False)
            with (
                mock.patch.object(S, "IDX_CSV", index_path),
                mock.patch.object(S, "NAMES_JSON", names_path),
                mock.patch.object(S.JG, "jiandi_signals") as signals,
            ):
                with self.assertRaisesRegex(SystemExit, "缺名称快照标签"):
                    S.do_scan(data_dir, pd.Timestamp(dates[-1]), lambda _: None, names=names)
                signals.assert_not_called()

    def test_missing_snapshot_fails_closed(self):
        with self.assertRaisesRegex(SystemExit, "data_full_names.json"):
            S.do_scan(Path("."), pd.Timestamp("2026-10-12"), lambda _: None, names={})


if __name__ == "__main__":
    unittest.main()
