# -*- coding: utf-8 -*-
"""Public Gushi forum index capture and fail-closed evidence review gate.

The scanner performs unauthenticated GETs against the five public community
forums only. It never follows the separate i.gushi.in product link, logs in,
posts, purchases, or changes account state. The review gate prevents a forum
claim or an untested strategy idea from being represented as locally validated.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:  # Keep --check and --selftest actionable on lean installations.
    requests = None
    BeautifulSoup = None

SITE = "https://www.gushi.in"
INVENTORY_SCHEMA = "gushi-public-forum-inventory/v1"
REVIEW_SCHEMA = "gushi-backtest-evidence-review/v1"
ALLOWED_HOSTS = {"gushi.in", "www.gushi.in"}
DECISIONS = {"采纳", "待实验", "不适用", "无法验证"}
BODY_STATES = {"full_body", "partial_body", "image_only", "login_gated", "listing_only", "request_error"}
FORUMS = {
    "1": "最好的地方",
    "5": "经验分享",
    "6": "社区共建",
    "7": "纯净水",
    "8": "指标公式",
}
TITLE_TERMS = (
    "回测", "未来函数", "样本外", "样本内", "收益曲线", "收益", "量化", "策略", "公式",
    "滑点", "成本", "交易", "验证", "复盘", "指标", "开盘", "成交", "仓位", "参数",
    "选股", "周期", "择时", "止损", "止盈", "复权", "因子", "筛选", "模拟盘", "统计",
    "绩效", "资金曲线", "胜率", "风控", "IC", "夏普", "最大回撤",
)


def _site_url(url: str) -> bool:
    try:
        return urlparse(url).scheme == "https" and urlparse(url).hostname in ALLOWED_HOSTS
    except (TypeError, ValueError):
        return False


def _screen_title(title: str) -> list[str]:
    lower = title.lower()
    return [term for term in TITLE_TERMS if term.lower() in lower]


def parse_listing_page(html: str, forum_id: str, requested_page: int, page_url: str) -> dict:
    """Parse one visible forum listing page; do not infer post-body content."""
    if BeautifulSoup is None:
        raise RuntimeError("BeautifulSoup4 is required for --scan")
    soup = BeautifulSoup(html, "html.parser")
    topics = []
    for row in soup.select("li.post-item"):
        anchor = row.select_one("a.post-title[href*='/topic/']") or row.select_one("a[href*='/topic/']")
        if not anchor:
            continue
        href = urljoin(page_url, anchor.get("href", ""))
        match = re.search(r"/topic/(\d+)(?:$|[/?#])", urlparse(href).path + ("?" if "?" in href else ""))
        topic_id = row.get("data-better-topic-list-id") or (match.group(1) if match else None)
        if not topic_id:
            continue
        title = (row.get("data-topic-list-filter-title") or " ".join(anchor.stripped_strings)).strip()
        activity = row.select_one(".tp-time")
        replies = row.get("data-better-topic-list-reply-count")
        if replies is None:
            reply_anchor = row.select_one("a[href*='#reply']")
            replies = " ".join(reply_anchor.stripped_strings) if reply_anchor else ""
        view_el = row.select_one(".tp-stats span[aria-label^='浏览']")
        views = " ".join(view_el.stripped_strings) if view_el else ""
        terms = _screen_title(title)
        candidate = bool(terms)
        topics.append({
            "topic_id": str(topic_id),
            "title": title,
            "url": f"{SITE}/topic/{topic_id}",
            "forum_id": str(row.get("data-topic-list-filter-forum-id") or forum_id),
            "forum": row.get("data-topic-list-filter-forum") or FORUMS.get(str(forum_id), "未知分类"),
            "listing_activity_text": " ".join(activity.stripped_strings) if activity else "",
            "listing_activity_title": activity.get("title", "") if activity else "",
            "listing_activity_timestamp": activity.get("data-timestamp", "") if activity else "",
            "reply_count": str(replies),
            "views_display": views,
            "body_read_status": "listing_only",
            "title_screen_terms": terms,
            "title_screen_decision": "无法验证" if candidate else "不适用",
            "title_screen_reason": (
                "标题命中高召回检索词；列表页未提供正文，须看正文/证据后才能评价方法。"
                if candidate else
                "标题未命中本轮高召回检索词；仅按标题排除本轮 agent 方法评估，不代表断言正文无相关内容。"
            ),
        })

    page_numbers = [requested_page]
    for anchor in soup.select("a[href*='sort=post']"):
        query = parse_qs(urlparse(urljoin(page_url, anchor.get("href", ""))).query)
        try:
            page_numbers.append(int(query.get("p", ["1"])[0]))
        except (TypeError, ValueError):
            continue
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return {
        "forum_id": str(forum_id),
        "forum": FORUMS.get(str(forum_id), page_title),
        "page": requested_page,
        "url": page_url,
        "http_status": 200,
        "page_title": page_title,
        "pages_max": max(page_numbers),
        "topics": topics,
    }


def capture_public_forum_index(pause_seconds: float = 0.12) -> dict:
    """Capture all post-date-sorted pages from the five public forum categories."""
    if requests is None or BeautifulSoup is None:
        raise RuntimeError("--scan requires requests and beautifulsoup4")
    pages: list[dict] = []
    errors: list[dict] = []
    for forum_id, forum_name in FORUMS.items():
        first_url = f"{SITE}/forum/{forum_id}?sort=post&p=1"
        try:
            response = requests.get(first_url, timeout=25, headers={"User-Agent": "Mozilla/5.0 (compatible; GushiBacktestEvidenceGate/1.0)"})
            if response.status_code != 200:
                errors.append({"forum_id": forum_id, "page": 1, "url": response.url, "status": response.status_code})
                continue
            first = parse_listing_page(response.text, forum_id, 1, response.url)
            first["forum"] = forum_name
            pages.append(first)
        except Exception as exc:
            errors.append({"forum_id": forum_id, "page": 1, "url": first_url, "error": f"{type(exc).__name__}: {exc}"})
            continue
        for page_no in range(2, first["pages_max"] + 1):
            if pause_seconds > 0:
                time.sleep(pause_seconds)
            url = f"{SITE}/forum/{forum_id}?sort=post&p={page_no}"
            try:
                response = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0 (compatible; GushiBacktestEvidenceGate/1.0)"})
                if response.status_code != 200:
                    errors.append({"forum_id": forum_id, "page": page_no, "url": response.url, "status": response.status_code})
                    continue
                page = parse_listing_page(response.text, forum_id, page_no, response.url)
                page["forum"] = forum_name
                pages.append(page)
            except Exception as exc:
                errors.append({"forum_id": forum_id, "page": page_no, "url": url, "error": f"{type(exc).__name__}: {exc}"})

    sources: dict[str, dict] = {}
    for page in pages:
        for topic in page["topics"]:
            sources[topic["topic_id"]] = topic
    categories = []
    for forum_id, forum_name in FORUMS.items():
        rows = [row for row in pages if row["forum_id"] == forum_id]
        categories.append({
            "forum_id": forum_id,
            "forum": forum_name,
            "pages_expected": rows[0]["pages_max"] if rows else 0,
            "pages_read": len(rows),
            "topics_listed_unique": sum(1 for item in sources.values() if item["forum_id"] == forum_id),
            "page_failures": sum(1 for item in errors if item["forum_id"] == forum_id),
        })
    result = {
        "schema_version": INVENTORY_SCHEMA,
        "site": SITE,
        "captured_at": date.today().isoformat(),
        "retrieval": "Unauthenticated read-only GET of public forum listings; no cookies, login, post, purchase, or account mutation.",
        "sort": "sort=post",
        "covered_forums": categories,
        "page_count_requested": sum(row["pages_expected"] for row in categories),
        "page_count_read": len(pages),
        "page_failures": errors,
        "unique_topic_count": len(sources),
        "title_candidate_count": sum(1 for item in sources.values() if item["title_screen_terms"]),
        "sources": sorted(sources.values(), key=lambda row: (int(row["forum_id"]), int(row["topic_id"]))),
    }
    return result


def _check_inventory(inventory: dict) -> list[str]:
    errors = []
    if inventory.get("schema_version") != INVENTORY_SCHEMA:
        errors.append("unsupported inventory schema_version")
    if not _site_url(inventory.get("site", "")):
        errors.append("inventory site must be gushi.in, not another subdomain")
    if inventory.get("page_failures"):
        errors.append(f"incomplete listing capture: {len(inventory['page_failures'])} page failures")
    if inventory.get("page_count_read") != inventory.get("page_count_requested"):
        errors.append("page_count_read differs from page_count_requested")
    sources = inventory.get("sources")
    if not isinstance(sources, list):
        return errors + ["inventory sources must be a list"]
    ids = [str(row.get("topic_id", "")) for row in sources]
    if not all(ids) or len(ids) != len(set(ids)):
        errors.append("inventory topic_id values must be nonempty and unique")
    if inventory.get("unique_topic_count") != len(sources):
        errors.append("unique_topic_count does not match sources length")
    candidates = 0
    for row in sources:
        tid = str(row.get("topic_id", ""))
        if not row.get("title") or not row.get("listing_activity_text"):
            errors.append(f"topic {tid}: title or visible listing date/activity missing")
        topic_path = urlparse(row.get("url", "")).path.rstrip("/")
        if not _site_url(row.get("url", "")) or topic_path != f"/topic/{tid}":
            errors.append(f"topic {tid}: source URL is invalid or outside gushi.in")
        terms = row.get("title_screen_terms")
        if not isinstance(terms, list):
            errors.append(f"topic {tid}: title_screen_terms must be a list")
            continue
        is_candidate = bool(terms)
        if is_candidate:
            candidates += 1
        expected = "无法验证" if is_candidate else "不适用"
        if row.get("title_screen_decision") != expected or not row.get("title_screen_reason"):
            errors.append(f"topic {tid}: title-only triage must state {expected} and a reason")
        if row.get("body_read_status") != "listing_only":
            errors.append(f"topic {tid}: listing capture must not claim body read")
    if inventory.get("title_candidate_count") != candidates:
        errors.append("title_candidate_count does not match source title screens")
    expected_forums = set(FORUMS)
    actual_forums = {str(row.get("forum_id")) for row in inventory.get("covered_forums", [])}
    if actual_forums != expected_forums:
        errors.append("inventory must explicitly cover forum/1, /5, /6, /7, /8")
    for row in inventory.get("covered_forums", []):
        if row.get("pages_read") != row.get("pages_expected"):
            errors.append(f"forum/{row.get('forum_id')}: page coverage incomplete")
    return errors


def _check_review(review: dict, inventory: dict, repo_root: Path) -> list[str]:
    errors = []
    if review.get("schema_version") != REVIEW_SCHEMA:
        errors.append("unsupported review schema_version")
    search = review.get("internal_search") or {}
    if search.get("status") != "login_required" or not search.get("observed_message"):
        errors.append("internal_search must record its actual access state and observed text")
    if search.get("absence_inference") is not False:
        errors.append("blocked/empty site search must not be interpreted as proof of absence")
    if "i.gushi.in" not in (review.get("excluded_platform_host") or ""):
        errors.append("review must explicitly exclude the separate i.gushi.in platform")
    inventory_by_id = {str(row["topic_id"]): row for row in inventory.get("sources", [])}
    assessments = review.get("assessments")
    if not isinstance(assessments, list) or not assessments:
        return errors + ["assessments must be a nonempty list"]
    assessment_ids = []
    for item in assessments:
        aid = str(item.get("assessment_id", ""))
        tid = str(item.get("topic_id", ""))
        assessment_ids.append(aid)
        if not aid or not tid or tid not in inventory_by_id:
            errors.append(f"assessment {aid or '<missing>'}: topic_id must match captured inventory")
            continue
        source = inventory_by_id[tid]
        if item.get("source_url") != source.get("url") or item.get("title") != source.get("title"):
            errors.append(f"assessment {aid}: title/url does not match captured topic {tid}")
        if item.get("body_status") not in BODY_STATES:
            errors.append(f"assessment {aid}: unsupported body_status")
        if item.get("decision") not in DECISIONS:
            errors.append(f"assessment {aid}: unsupported decision")
            continue
        if not item.get("reason") or not item.get("applicability_conditions"):
            errors.append(f"assessment {aid}: reason and applicability_conditions are required")
        decision = item["decision"]
        if decision == "采纳":
            if item.get("body_status") != "full_body":
                errors.append(f"assessment {aid}: adopted method requires full body access")
            if item.get("claim_type") not in {"process_method", "validation_procedure"}:
                errors.append(f"assessment {aid}: only process methods/procedures may be adopted")
            verification = item.get("local_verification") or {}
            if verification.get("result") != "PASS" or verification.get("positive_control") != "PASS" or verification.get("negative_control") != "PASS":
                errors.append(f"assessment {aid}: adoption requires local PASS plus positive and negative controls")
            paths = verification.get("evidence_files") or []
            if not paths:
                errors.append(f"assessment {aid}: adoption requires durable evidence file paths")
            for rel in paths:
                p = (repo_root / rel).resolve()
                if not p.is_relative_to(repo_root.resolve()):
                    errors.append(f"assessment {aid}: evidence path escapes repository")
                elif not p.is_file():
                    errors.append(f"assessment {aid}: evidence file missing: {rel}")
            if item.get("production_rule_change") is not False:
                errors.append(f"assessment {aid}: forum review must not silently alter production rules")
        elif decision == "待实验":
            if not item.get("experiment_plan"):
                errors.append(f"assessment {aid}: trial status requires a concrete experiment plan")
            if item.get("production_rule_change") is not False:
                errors.append(f"assessment {aid}: trial status must retain zero production changes")
        elif decision in {"不适用", "无法验证"}:
            if not item.get("reason"):
                errors.append(f"assessment {aid}: excluded/unverified status requires a reason")
        if item.get("claim_type") == "performance_claim" and decision == "采纳":
            errors.append(f"assessment {aid}: source performance claims cannot be adopted as facts")
    if len(assessment_ids) != len(set(assessment_ids)):
        errors.append("assessment_id values must be unique")
    summary = review.get("inventory_summary") or {}
    for key in ("page_count_read", "unique_topic_count", "title_candidate_count"):
        if summary.get(key) != inventory.get(key):
            errors.append(f"review inventory_summary.{key} differs from captured inventory")
    return errors


def validate_documents(inventory: dict, review: dict, repo_root: Path) -> list[str]:
    return _check_inventory(inventory) + _check_review(review, inventory, repo_root)


def _fixture_documents(root: Path) -> tuple[dict, dict]:
    (root / "fixture_positive_control.txt").write_text("oracle must cause the signal to fire", encoding="utf-8")
    (root / "fixture_negative_control.txt").write_text("normal causal strategy must remain unchanged", encoding="utf-8")
    sources = [
        {"topic_id": "465", "title": "回测中的未来函数排查清单", "url": "https://www.gushi.in/topic/465", "forum_id": "5", "forum": "经验分享", "listing_activity_text": "2026-09-27", "listing_activity_title": "", "listing_activity_timestamp": "", "reply_count": "0", "views_display": "", "body_read_status": "listing_only", "title_screen_terms": ["回测"], "title_screen_decision": "无法验证", "title_screen_reason": "listing-only"},
        {"topic_id": "1009", "title": "竞价多头策略历史数据", "url": "https://www.gushi.in/topic/1009", "forum_id": "1", "forum": "最好的地方", "listing_activity_text": "昨天", "listing_activity_title": "", "listing_activity_timestamp": "", "reply_count": "0", "views_display": "", "body_read_status": "listing_only", "title_screen_terms": ["策略"], "title_screen_decision": "无法验证", "title_screen_reason": "listing-only"},
    ]
    inventory = {"schema_version": INVENTORY_SCHEMA, "site": SITE, "page_count_requested": 5, "page_count_read": 5, "page_failures": [], "unique_topic_count": 2, "title_candidate_count": 2, "covered_forums": [{"forum_id": k, "forum": v, "pages_expected": 1, "pages_read": 1, "topics_listed_unique": 0, "page_failures": 0} for k, v in FORUMS.items()], "sources": sources}
    review = {"schema_version": REVIEW_SCHEMA, "inventory_summary": {"page_count_read": 5, "unique_topic_count": 2, "title_candidate_count": 2}, "internal_search": {"status": "login_required", "observed_message": "请登录后操作", "absence_inference": False}, "excluded_platform_host": "i.gushi.in", "assessments": [
        {"assessment_id": "465-process", "topic_id": "465", "source_url": "https://www.gushi.in/topic/465", "title": sources[0]["title"], "source_date_display": "2026-09-27", "body_status": "full_body", "claim_type": "process_method", "decision": "采纳", "source_method": "五维未来函数核查流程", "reason": "仅采纳为审计清单，不接受帖中性能泛化数字", "applicability_conditions": "有逐笔/逐 bar 可重放的日线 A 股规则", "production_rule_change": False, "local_verification": {"result": "PASS", "positive_control": "PASS", "negative_control": "PASS", "evidence_files": ["fixture_positive_control.txt", "fixture_negative_control.txt"]}},
        {"assessment_id": "1009-claim", "topic_id": "1009", "source_url": "https://www.gushi.in/topic/1009", "title": sources[1]["title"], "source_date_display": "昨天（列表显示）", "body_status": "login_gated", "claim_type": "performance_claim", "decision": "无法验证", "reason": "正文被 TL1 限制", "applicability_conditions": "不适用，未读正文"}
    ]}
    return inventory, review


def run_selftest() -> int:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="gushi-evidence-gate-") as td:
        root = Path(td)
        inventory, review = _fixture_documents(root)
        cases = []
        cases.append(("valid controlled adoption + gated unverified", validate_documents(inventory, review, root) == []))
        bad = json.loads(json.dumps(review))
        bad["assessments"][0]["local_verification"]["positive_control"] = "NOT_RUN"
        cases.append(("adoption without positive control rejected", bool(validate_documents(inventory, bad, root))))
        bad = json.loads(json.dumps(review))
        bad["assessments"][0]["source_url"] = "https://i.gushi.in/topic/465"
        cases.append(("platform subdomain substitution rejected", bool(validate_documents(inventory, bad, root))))
        bad = json.loads(json.dumps(review))
        bad["assessments"][1]["decision"] = "采纳"
        bad["assessments"][1]["claim_type"] = "process_method"
        bad["assessments"][1]["local_verification"] = {"result": "PASS", "positive_control": "PASS", "negative_control": "PASS", "evidence_files": ["fixture_positive_control.txt"]}
        bad["assessments"][1]["production_rule_change"] = False
        cases.append(("gated body cannot be adopted", bool(validate_documents(inventory, bad, root))))
        bad = json.loads(json.dumps(review))
        bad["assessments"][1]["reason"] = ""
        cases.append(("missing reason rejected", bool(validate_documents(inventory, bad, root))))
        bad = json.loads(json.dumps(review))
        bad["assessments"][1]["source_url"] = "https://www.gushi.in/topic/123"
        cases.append(("source URL must match inventory ID", bool(validate_documents(inventory, bad, root))))
        bad = json.loads(json.dumps(review))
        bad["assessments"][1]["decision"] = "待实验"
        bad["assessments"][1]["body_status"] = "full_body"
        bad["assessments"][1]["experiment_plan"] = "replay"
        cases.append(("trial needs zero production change", bool(validate_documents(inventory, bad, root))))
        failed = [name for name, passed in cases if not passed]
        for name, passed in cases:
            print(f"[selftest] {'PASS' if passed else 'FAIL'} {name}")
        if failed:
            return 1
        print(f"selftest passed: {len(cases)}/{len(cases)}")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gushi public forum source inventory and backtest evidence gate")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scan", action="store_true", help="read-only scan of public listing pages in forum/1,5,6,7,8")
    mode.add_argument("--check", action="store_true", help="validate a captured inventory and reviewed-claims ledger")
    mode.add_argument("--selftest", action="store_true", help="offline positive/negative gate tests")
    parser.add_argument("--out", type=Path, help="inventory JSON output for --scan")
    parser.add_argument("--inventory", type=Path, help="inventory JSON input for --check")
    parser.add_argument("--review", type=Path, help="review JSON input for --check")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    if args.selftest:
        return run_selftest()
    if args.scan:
        if args.out is None:
            parser.error("--scan requires --out PATH")
        out = args.out if args.out.is_absolute() else args.repo_root / args.out
        if out.exists():
            print(f"refusing to overwrite existing inventory: {out}", file=sys.stderr)
            return 2
        result = capture_public_forum_index()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"captured pages={result['page_count_read']}/{result['page_count_requested']} topics={result['unique_topic_count']} title_candidates={result['title_candidate_count']} failures={len(result['page_failures'])}")
        print(f"wrote {out}")
        return 0 if not result["page_failures"] else 1
    if args.inventory is None or args.review is None:
        parser.error("--check requires --inventory PATH --review PATH")
    try:
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
        review = json.loads(args.review.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"cannot read JSON input: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    errors = validate_documents(inventory, review, args.repo_root.resolve())
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    decisions = {}
    for item in review["assessments"]:
        decisions[item["decision"]] = decisions.get(item["decision"], 0) + 1
    print("PASS: inventory coverage and claim/evidence gate")
    print(f"forum_pages={inventory['page_count_read']}/{inventory['page_count_requested']} topics={inventory['unique_topic_count']} title_candidates={inventory['title_candidate_count']} reviewed={len(review['assessments'])}")
    print("decisions=" + json.dumps(decisions, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
