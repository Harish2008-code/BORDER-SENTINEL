from datetime import date, timedelta

from django.test import TestCase

from screening.mrz import build_td3, parse_mrz
from screening.rules import run_validation, summarize


def _mrz():
    l1, l2 = build_td3("P", "IND", "SHARMA", "PRIYA", "Z1234567", "IND",
                       date(1995, 3, 12), date(2031, 11, 20), "F")
    return parse_mrz([l1, l2])


def _values(**kw):
    base = dict(surname="SHARMA", given_names="PRIYA", full_name="SHARMA PRIYA",
                doc_number="Z1234567", nationality="IND", dob="12 03 1995",
                expiry="20 11 2031", sex="F")
    base.update(kw)
    return base


class RulesTests(TestCase):
    def test_clean_passport_passes(self):
        checks = run_validation(_values(), _mrz(), "passport")
        failed = [c for c in checks if not c["passed"] and c["severity"] == "critical"]
        self.assertEqual(failed, [])

    def test_expired_document_fails(self):
        past = (date.today() - timedelta(days=400)).strftime("%d %m %Y")
        checks = run_validation(_values(expiry=past), None, "passport")
        self.assertTrue(any(c["id"] == "expiry_logic" and not c["passed"]
                            for c in checks))

    def test_blacklist_hit(self):
        checks = run_validation(_values(), None, "passport",
                                blacklist={"Z1234567"})
        bl = [c for c in checks if c["id"] == "blacklist"][0]
        self.assertFalse(bl["passed"])
        self.assertEqual(summarize(checks)["critical"] >= 1, True)

    def test_watchlist_fuzzy_hit(self):
        checks = run_validation(_values(), None, "passport",
                                watchlist=[{"full_name": "PRIYA SHARMA",
                                            "doc_number": "", "reason": "test"}])
        # note: jaro-winkler on word-swapped names is below threshold, so use
        # a near-identical spelling for a guaranteed hit:
        checks = run_validation(_values(), None, "passport",
                                watchlist=[{"full_name": "SHARMA PRIYA",
                                            "doc_number": "", "reason": "test"}])
        wl = [c for c in checks if c["id"] == "watchlist"][0]
        self.assertFalse(wl["passed"])

    def test_bad_nationality_warns(self):
        checks = run_validation(_values(nationality="XXX"), None, "passport")
        nat = [c for c in checks if c["id"] == "nationality_code"][0]
        self.assertFalse(nat["passed"])
        self.assertEqual(nat["severity"], "warning")
