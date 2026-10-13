import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))
import gushi_backtest_evidence_gate as gate


class GushiEvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gushi-evidence-test-")
        self.root = Path(self.temp.name)
        (self.root / "evidence.json").write_text("{}", encoding="utf-8")
        self.inventory = self.make_inventory()
        self.review = self.make_review()

    def tearDown(self):
        self.temp.cleanup()

    def make_inventory(self):
        categories = [
            {"forum_id": fid, "forum": name, "pages_expected": 1,
             "pages_read": 1, "topics_listed_unique": 1, "page_failures": 0}
            for fid, name in gate.FORUMS.items()
        ]
        sources = [
            {"topic_id": "465", "title": "未来函数排查清单", "url": "https://www.gushi.in/topic/465",
             "forum_id": "5", "forum": "经验分享", "listing_activity_text": "2026-09-27",
             "body_read_status": "listing_only", "title_screen_terms": ["未来函数"],
             "title_screen_decision": "无法验证", "title_screen_reason": "仅标题筛选，未读正文。"},
            {"topic_id": "1009", "title": "历史数据策略", "url": "https://www.gushi.in/topic/1009",
             "forum_id": "1", "forum": "最好的地方", "listing_activity_text": "昨天",
             "body_read_status": "listing_only", "title_screen_terms": ["策略"],
             "title_screen_decision": "无法验证", "title_screen_reason": "仅标题筛选，未读正文。"},
        ]
        return {"schema_version": gate.INVENTORY_SCHEMA, "site": gate.SITE,
                "page_count_requested": 5, "page_count_read": 5, "page_failures": [],
                "unique_topic_count": 2, "title_candidate_count": 2,
                "covered_forums": categories, "sources": sources}

    def make_review(self):
        sources = {row["topic_id"]: row for row in self.inventory["sources"]}
        return {
            "schema_version": gate.REVIEW_SCHEMA,
            "inventory_summary": {k: self.inventory[k] for k in
                                  ("page_count_read", "unique_topic_count", "title_candidate_count")},
            "internal_search": {"status": "login_required", "observed_message": "请登录后操作",
                                "absence_inference": False},
            "excluded_platform_host": "i.gushi.in",
            "assessments": [
                {"assessment_id": "465-five-dimensions", "topic_id": "465",
                 "title": sources["465"]["title"], "source_url": sources["465"]["url"],
                 "source_date_display": "2026-09-27", "body_status": "full_body",
                 "claim_type": "process_method", "decision": "采纳",
                 "source_method": "将前视检查分成指标、K线/可用时点、选股、执行和样本/参数/成本五类。",
                 "reason": "仅采纳核查维度；原帖泛化百分比不采纳。",
                 "applicability_conditions": "日线策略；判断须映射到实际可用时点与成交时钟。",
                 "production_rule_change": False,
                 "local_verification": {"result": "PASS", "positive_control": "PASS",
                                         "negative_control": "PASS", "evidence_files": ["evidence.json"]}},
                {"assessment_id": "1009-gated", "topic_id": "1009",
                 "title": sources["1009"]["title"], "source_url": sources["1009"]["url"],
                 "source_date_display": "昨天（列表显示）", "body_status": "login_gated",
                 "claim_type": "performance_claim", "decision": "无法验证",
                 "reason": "正文需要 TL1；未升级权限或消耗积分。",
                 "applicability_conditions": "不适用，正文不可读。"},
            ],
        }

    def errors(self, inventory=None, review=None):
        return gate.validate_documents(inventory or self.inventory, review or self.review, self.root)

    def test_valid_adopted_method_and_gated_unverified_claim_pass(self):
        self.assertEqual(self.errors(), [])

    def test_inventory_rejects_i_gushi_platform(self):
        self.inventory["sources"][0]["url"] = "https://i.gushi.in/topic/465"
        self.assertTrue(any("outside gushi.in" in e for e in self.errors()))

    def test_adoption_requires_positive_and_negative_controls(self):
        self.review["assessments"][0]["local_verification"]["positive_control"] = "NOT_RUN"
        self.assertTrue(any("positive and negative controls" in e for e in self.errors()))

    def test_adoption_rejects_performance_claim(self):
        self.review["assessments"][0]["claim_type"] = "performance_claim"
        self.assertTrue(any("only process methods" in e for e in self.errors()))
        self.assertTrue(any("performance claims cannot be adopted" in e for e in self.errors()))

    def test_gated_body_cannot_be_adopted(self):
        item = self.review["assessments"][1]
        item.update({"decision": "采纳", "claim_type": "process_method", "source_method": "unseen",
                     "applicability_conditions": "unknown", "production_rule_change": False,
                     "local_verification": {"result": "PASS", "positive_control": "PASS",
                                             "negative_control": "PASS", "evidence_files": ["evidence.json"]}})
        self.assertTrue(any("adopted method requires full body access" in e for e in self.errors()))

    def test_trial_requires_plan_and_no_production_change(self):
        item = self.review["assessments"][1]
        item.update({"decision": "待实验", "body_status": "full_body", "experiment_plan": "replay"})
        item["production_rule_change"] = True
        self.assertTrue(any("trial status must retain zero production changes" in e for e in self.errors()))

    def test_missing_reason_rejected(self):
        self.review["assessments"][1]["reason"] = ""
        self.assertTrue(any("reason and applicability_conditions" in e for e in self.errors()))

    def test_source_url_must_match_captured_topic(self):
        self.review["assessments"][1]["source_url"] = "https://www.gushi.in/topic/465"
        self.assertTrue(any("does not match captured topic" in e for e in self.errors()))

    def test_duplicate_topic_id_rejected(self):
        self.inventory["sources"].append(dict(self.inventory["sources"][0]))
        self.inventory["unique_topic_count"] = 3
        self.assertTrue(any("nonempty and unique" in e for e in self.errors()))

    def test_listing_parser_records_topic_id_date_and_page_count(self):
        html = '''<html><head><title>经验分享</title></head><body>
        <li class="post-item" data-better-topic-list-id="465" data-better-topic-list-reply-count="7"
            data-topic-list-filter-forum="经验分享" data-topic-list-filter-forum-id="5"
            data-topic-list-filter-title="未来函数排查">
          <a class="post-title" href="/topic/465">未来函数排查</a>
          <span class="tp-time" title="最新回帖时间：2026-09-27 09:15:34" data-timestamp="1790471734">2026-09-27</span>
        </li><a href="/forum/5?sort=post&amp;p=3">3</a></body></html>'''
        page = gate.parse_listing_page(html, "5", 2, "https://www.gushi.in/forum/5?sort=post&p=2")
        self.assertEqual(page["pages_max"], 3)
        self.assertEqual(page["topics"][0]["topic_id"], "465")
        self.assertEqual(page["topics"][0]["listing_activity_text"], "2026-09-27")
        self.assertEqual(page["topics"][0]["title_screen_decision"], "无法验证")


if __name__ == "__main__":
    unittest.main(verbosity=2)
