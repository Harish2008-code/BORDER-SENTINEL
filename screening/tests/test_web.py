import shutil
import tempfile

from django.conf import settings
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.urls import reverse

from screening import synthetic

_TMP = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_TMP)
class WebAndApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dir = tempfile.mkdtemp()
        cls.paths = synthetic.generate_demo_docs(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)
        super().tearDownClass()

    def test_pages_render(self):
        for name in ("dashboard", "upload", "records", "watchlist"):
            resp = self.client.get(reverse(f"screening:{name}"))
            self.assertEqual(resp.status_code, 200, name)

    def test_api_health(self):
        resp = self.client.get(reverse("screening:api_health"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_upload_flow_and_api(self):
        with open(self.paths["clean_passport"], "rb") as fh:
            resp = self.client.post(reverse("screening:upload"),
                                    {"document": fh})
        self.assertEqual(resp.status_code, 302)
        record_url = resp.url
        resp = self.client.get(record_url)
        self.assertEqual(resp.status_code, 200)
        pk = record_url.rstrip("/").split("/")[-1]

        api = self.client.get(reverse("screening:api_record", args=[pk]))
        self.assertEqual(api.status_code, 200)
        body = api.json()
        self.assertEqual(body["risk_level"], "LOW")
        self.assertTrue(body["audit_chain_valid"])

    def test_api_screen_multipart(self):
        with open(self.paths["tampered_photo"], "rb") as fh:
            resp = self.client.post(reverse("screening:api_screen"),
                                    {"document": fh})
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        body = resp.json()
        self.assertEqual(body["doc_type"], "passport")
        self.assertIn("modules", body)

    def test_api_screen_imposter_high_risk(self):
        with open(self.paths["tampered_photo"], "rb") as fh, \
             open(str(settings.DEMO_ASSETS_DIR / "subject_a_live_capture.jpg"), "rb") as lf:
            resp = self.client.post(reverse("screening:api_screen"),
                                    {"document": fh, "live_photo": lf})
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["risk_level"], "HIGH", body["scoring"])
        self.assertFalse(body["face"]["matched"])
