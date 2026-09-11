import shutil
import tempfile

from django.conf import settings
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from screening import synthetic
from screening.models import ExpiredDocument, ScreeningRecord, WatchlistEntry
from screening.pipeline import run_screening

_TMP = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_TMP)
class PipelineTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dir = tempfile.mkdtemp()
        cls.paths = synthetic.generate_demo_docs(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)
        super().tearDownClass()

    def _store(self, key, name):
        with open(self.paths[key], "rb") as fh:
            rel = default_storage.save(f"documents/{name}", fh)
        return rel

    def test_clean_passport_low_risk(self):
        rel = self._store("clean_passport", "clean.jpg")
        res = run_screening(rel)
        self.assertEqual(res["doc_type"], "passport")
        self.assertEqual(res["doc_number"], "Z1234567")
        self.assertEqual(res["risk"]["level"], "LOW", res["risk"])
        self.assertTrue(res["validation_summary"]["critical"] == 0)
        rec = ScreeningRecord.objects.get(pk=res["record_id"])
        self.assertTrue(rec.verify_audit_chain())

    def test_blacklisted_document_high_risk(self):
        ExpiredDocument.objects.create(doc_number="B4444444", reason="stolen")
        rel = self._store("blacklisted_passport", "bl.jpg")
        res = run_screening(rel)
        self.assertEqual(res["risk"]["level"], "HIGH", res["risk"])
        failed_ids = {c["id"] for c in res["checks"] if not c["passed"]}
        self.assertIn("blacklist", failed_ids)

    def test_watchlisted_traveller_flagged(self):
        WatchlistEntry.objects.create(full_name="VIKRAM SINGH", reason="red notice")
        rel = self._store("watchlist_passport", "wl.jpg")
        res = run_screening(rel)
        failed_ids = {c["id"] for c in res["checks"] if not c["passed"]}
        self.assertIn("watchlist", failed_ids)
        self.assertGreaterEqual(res["risk"]["score"], 30)

    def test_face_match_and_mismatch(self):
        rel = self._store("clean_passport", "clean2.jpg")
        with open(settings.DEMO_ASSETS_DIR / "subject_a_live_capture.jpg", "rb") as fh:
            live_ok = default_storage.save("live/a.jpg", fh)
        with open(settings.DEMO_ASSETS_DIR / "subject_b_passport_photo.jpg", "rb") as fh:
            live_bad = default_storage.save("live/b.jpg", fh)
        ok = run_screening(rel, live_ok)
        self.assertTrue(ok["face"]["matched"], ok["face"])
        bad = run_screening(rel, live_bad)
        self.assertFalse(bad["face"]["matched"], bad["face"])
        self.assertGreater(bad["risk"]["score"], ok["risk"]["score"])

    def test_visa_screening(self):
        rel = self._store("visa", "visa.jpg")
        res = run_screening(rel)
        self.assertEqual(res["doc_type"], "visa")
        self.assertIn("visa_number", res["extraction"]["values"])

    def test_dob_forgery_validation_gate(self):
        rel = self._store("tampered_dob", "dob.jpg")
        res = run_screening(rel)
        failed = {c["id"] for c in res["checks"] if not c["passed"]}
        self.assertIn("dob_consistency", failed)
        self.assertEqual(res["risk"]["level"], "MEDIUM", res["risk"])

    def test_photo_swap_with_live_is_high(self):
        rel = self._store("tampered_photo", "swap.jpg")
        with open(settings.DEMO_ASSETS_DIR / "subject_a_live_capture.jpg", "rb") as fh:
            live = default_storage.save("live/ok.jpg", fh)
        res = run_screening(rel, live)
        self.assertFalse(res["face"]["matched"])
        self.assertEqual(res["risk"]["level"], "HIGH", res["risk"])
