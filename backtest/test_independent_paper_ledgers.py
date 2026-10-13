# -*- coding: utf-8 -*-
"""独立纸面账本纯状态转换测试；所有状态与行情均为内存夹具。"""
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fund = load_module("fund_rotation_paper_test", "fund_rotation_paper.py")
sentinel = load_module("sentinel_return_paper_test", "sentinel_return_paper.py")


class FundRotationLedgerTests(unittest.TestCase):
    def make_pool(self, day, fund_day=None, codes=("000001",)):
        fund_day = fund_day or day
        details = {code: {"name": "基金" + code, "px": 1.0, "date": fund_day} for code in codes}
        return {"as_of": day, "fund_as_of": fund_day, "tiers": {"基金": list(codes)},
                "details": details, "market_gate": {"open": True}}

    def test_stale_pool_seeds_flat_account_and_never_creates_order(self):
        stale = self.make_pool("2026-01-02", "2026-01-01")
        state = fund.step(None, stale, {"000001": [("2026-01-01", 1.0)]}, "2026-01-05",
                          started_at="fixture")
        self.assertEqual(state["status"], "SIGNAL_SOURCE_STALE")
        self.assertEqual(state["nav"], fund.INITIAL_CASH)
        self.assertEqual(state["cum_return_pct"], 0.0)
        self.assertEqual(state["positions"], {})
        self.assertEqual(state["pending_orders"], {})
        self.assertEqual(state["fills"], [])

    def test_stale_seed_retries_when_same_day_pool_refreshes(self):
        stale = self.make_pool("2026-01-02", "2026-01-01")
        navs = {"000001": [("2026-01-05", 1.0)]}
        state = fund.step(None, stale, navs, "2026-01-05", started_at="fixture")
        self.assertEqual(state["status"], "SIGNAL_SOURCE_STALE")
        fresh = self.make_pool("2026-01-05", "2026-01-05")
        state = fund.step(state, fresh, navs, "2026-01-05")
        self.assertEqual(state["status"], "WAITING_FOR_NEXT_NAV")
        self.assertEqual(state["pending_orders"]["000001"]["side"], "buy")
        self.assertEqual(state["fills"], [])
        replay = fund.step(state, fresh, navs, "2026-01-05")
        self.assertIs(replay, state)

    def test_signal_day_waits_then_buy_mark_sell_and_charge_both_sides(self):
        navs = {"000001": [("2026-01-05", 1.0), ("2026-01-06", 1.1),
                           ("2026-01-07", 1.2), ("2026-01-08", 1.3)]}
        state = fund.step(None, self.make_pool("2026-01-05"), navs, "2026-01-05",
                          started_at="fixture")
        self.assertEqual(state["n_fills"], 0)
        self.assertEqual(state["positions"], {})
        self.assertEqual(state["pending_orders"]["000001"]["status"], "WAITING_FOR_NEXT_NAV")

        state = fund.step(state, self.make_pool("2026-01-06"), navs, "2026-01-06")
        self.assertEqual(state["fills"][0]["side"], "buy")
        self.assertGreater(state["fills"][0]["fee"], 0)
        self.assertGreater(state["positions"]["000001"]["units"], 0)
        self.assertEqual(state["positions"]["000001"]["entry_date"], "2026-01-06")
        self.assertAlmostEqual(state["nav"], state["cash"] + state["market_value"], places=3)
        self.assertAlmostEqual(state["cum_return_pct"], -0.05, delta=0.002)

        state = fund.step(state, self.make_pool("2026-01-07", codes=()), navs, "2026-01-07")
        self.assertIn("000001", state["pending_orders"])
        self.assertEqual(state["pending_orders"]["000001"]["side"], "sell")
        state = fund.step(state, self.make_pool("2026-01-08", codes=()), navs, "2026-01-08")
        self.assertEqual(state["positions"], {})
        self.assertEqual([fill["side"] for fill in state["fills"]], ["buy", "sell"])
        self.assertGreater(state["fills"][1]["fee"], 0)
        self.assertGreater(state["n_completed_trades"], 0)
        self.assertGreater(state["nav"], fund.INITIAL_CASH)
        self.assertAlmostEqual(state["cum_return_pct"], (state["nav"] / fund.INITIAL_CASH - 1) * 100, places=3)

    def test_partial_buy_keeps_remaining_units_pending(self):
        state = fund.new_state("2026-01-05", "fixture")
        state["cash"] = 10_000.0
        state["pending_orders"] = {"000001": {
            "code": "000001", "name": "基金", "side": "buy", "target_units": 20_000.0,
            "signal_fund_asof": "2026-01-05", "eligible_after": "2026-01-05"}}
        fund._fill_orders(state, {"000001": [("2026-01-06", 1.0)]}, "2026-01-06")
        self.assertGreater(state["positions"]["000001"]["units"], 0)
        self.assertLess(state["positions"]["000001"]["units"], 20_000.0)
        self.assertEqual(state["pending_orders"]["000001"]["status"], "PARTIAL_BUY_WAITING_NEXT_NAV")
        self.assertGreater(state["fills"][0]["fee"], 0)

    def test_same_day_replay_is_idempotent(self):
        pool = self.make_pool("2026-01-05")
        navs = {"000001": [("2026-01-05", 1.0)]}
        state = fund.step(None, pool, navs, "2026-01-05", started_at="fixture")
        replay = fund.step(state, pool, navs, "2026-01-05")
        self.assertIs(replay, state)
        self.assertEqual(len(state["fills"]), 0)


class SentinelReturnLedgerTests(unittest.TestCase):
    def setUp(self):
        # Simulated daily trading calendar; first 16 bars establish a mixed RSI history.
        self.days = ["2026-01-%02d" % day for day in range(1, 21)]
        self.index = [{"date": day, "close": 100.0} for day in self.days]
        closes = [100.0 + (0.1 if i % 2 else 0.0) for i in range(16)]
        closes[-1] = 100.0
        self.code = "sh600001"
        self.base_bars = [{"date": self.days[i], "open": closes[i], "close": closes[i]}
                          for i in range(16)]
        self.d0, self.d1, self.d2, self.d3 = self.days[15:19]

    def trigger_pool(self, day, triggered=True, rows=None):
        rows = rows if rows is not None else [{"code": self.code, "name": "测试主板", "cnt": 3}]
        return {"as_of": day, "triggered": triggered, "threshold": 30,
                "as_of_resonance": 31 if triggered else 0,
                "pool": rows if triggered else []}

    def test_flat_seed_and_no_trigger_has_real_zero_return(self):
        state = sentinel.step(None, self.trigger_pool(self.d0, False), self.index[:16], {}, self.d0,
                              started_at="fixture")
        self.assertEqual(state["status"], "FLAT_NO_TRIGGER")
        self.assertEqual(state["as_of"], self.d0)
        for port in state["portfolios"].values():
            self.assertEqual(port["nav"], sentinel.SEED_NAV)
            self.assertEqual(port["cum_net_return_pct"], 0.0)
            self.assertEqual(port["positions"], {})
            self.assertEqual(port["n_fills"], 0)

    def test_t1_entry_mark_rsi_exit_and_separate_round_trip_costs(self):
        bars = {self.code: list(self.base_bars) + [
            {"date": self.d1, "open": 100.0, "close": 100.0},
            {"date": self.d2, "open": 100.0, "close": 110.0},
            {"date": self.d3, "open": 110.0, "close": 110.0},
        ]}
        state = sentinel.step(None, self.trigger_pool(self.d0), self.index[:16], bars, self.d0,
                              started_at="fixture")
        self.assertEqual(state["pending_entries"]["status"], "WAITING_T1_OPEN")
        self.assertEqual(sum(p["n_fills"] for p in state["portfolios"].values()), 0)

        state = sentinel.step(state, self.trigger_pool(self.d1, False), self.index[:17], bars, self.d1)
        for port in state["portfolios"].values():
            self.assertIn(self.code, port["positions"])
            self.assertEqual(port["positions"][self.code]["entry_date"], self.d1)
            self.assertEqual(port["fills"][0]["side"], "buy")
            self.assertEqual(port["fills"][0]["fee"], 0.0)

        state = sentinel.step(state, self.trigger_pool(self.d2, False), self.index[:18], bars, self.d2)
        for port in state["portfolios"].values():
            self.assertAlmostEqual(port["nav"], 102000.0, places=2)
            self.assertIsNone(port["positions"][self.code]["exit_date"])
            self.assertEqual(port["positions"][self.code]["exit_signal_date"], self.d2)

        state = sentinel.step(state, self.trigger_pool(self.d3, False), self.index, bars, self.d3)
        low = state["portfolios"]["0.20%"]
        high = state["portfolios"]["1.15%"]
        self.assertEqual(low["positions"], {})
        self.assertEqual(low["n_completed_trades"], 1)
        self.assertEqual(high["n_completed_trades"], 1)
        self.assertEqual(low["closed_trades"][0]["exit_date"], self.d3)
        self.assertAlmostEqual(low["nav"], 101960.0, delta=0.1)
        self.assertAlmostEqual(high["nav"], 101770.0, delta=0.1)
        self.assertGreater(low["closed_trades"][0]["fee"], 0)
        self.assertGreater(high["closed_trades"][0]["fee"], low["closed_trades"][0]["fee"])
        self.assertAlmostEqual(low["cum_net_return_pct"], 1.96, places=2)
        self.assertAlmostEqual(high["cum_net_return_pct"], 1.77, places=2)

    def test_missing_t1_open_remains_pending_and_never_fills_t2(self):
        bars = {self.code: list(self.base_bars) + [
            {"date": self.d1, "open": None, "close": None},
            {"date": self.d2, "open": 100.0, "close": 100.0},
        ]}
        state = sentinel.step(None, self.trigger_pool(self.d0), self.index[:16], bars, self.d0,
                              started_at="fixture")
        state = sentinel.step(state, self.trigger_pool(self.d1, False), self.index[:17], bars, self.d1)
        self.assertEqual(state["pending_entries"]["status"], "MISSING_T1_OPEN_OR_PRICE")
        state = sentinel.step(state, self.trigger_pool(self.d2, False), self.index[:18], bars, self.d2)
        self.assertEqual(state["pending_entries"]["status"], "MISSED_T1_OPEN_OR_DATA")
        self.assertEqual(state["status"], "MISSED_T1_OPEN_OR_DATA")
        for port in state["portfolios"].values():
            self.assertEqual(port["positions"], {})
            self.assertEqual(port["n_fills"], 0)
            self.assertEqual(port["nav"], sentinel.SEED_NAV)

    def test_same_day_replay_does_not_duplicate_signal_or_fills(self):
        state = sentinel.step(None, self.trigger_pool(self.d0), self.index[:16], {}, self.d0,
                              started_at="fixture")
        replay = sentinel.step(state, self.trigger_pool(self.d0), self.index[:16], {}, self.d0)
        self.assertIs(replay, state)
        self.assertEqual(len(state["signals"]), 1)
        self.assertEqual(sum(p["n_fills"] for p in state["portfolios"].values()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
