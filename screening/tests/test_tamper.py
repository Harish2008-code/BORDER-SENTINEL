import os
import shutil
import tempfile

import cv2
from django.test import TestCase

from screening import synthetic, tamper


class TamperTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dir = tempfile.mkdtemp()
        cls.paths = synthetic.generate_demo_docs(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)
        super().tearDownClass()

    def _suite(self, path, with_regions=False):
        img = cv2.imread(path)
        from screening import faces as F
        det = F.detect_faces(img)
        regions = []
        if with_regions:
            from screening import ocr_engine
            regions = list(ocr_engine.extract_fields(img)["regions"].values())
        return tamper.run_tamper_suite(img, path,
                                       face_bbox=det[0] if det else None,
                                       text_regions=regions)

    def test_clean_document_scores_low(self):
        res = self._suite(self.paths["clean_passport"], with_regions=True)
        self.assertLess(res["score"], 15, res["detectors"])

    def test_metadata_fingerprint_detected(self):
        res = self._suite(self.paths["metadata_forgery"])
        self.assertGreaterEqual(res["score"], 30)
        md = [d for d in res["detectors"] if d["name"] == "Metadata Forensics"][0]
        self.assertGreaterEqual(md["score"], 30)
        self.assertIn("Photoshop", md["detail"])

    def test_clean_metadata_has_no_fingerprint(self):
        det = tamper.metadata_detector(self.paths["clean_passport"])
        self.assertEqual(det["score"], 0)

    def test_detectors_return_regions_structure(self):
        res = self._suite(self.paths["clean_passport"])
        self.assertIn("score", res)
        self.assertEqual(len(res["detectors"]), 6)
        for d in res["detectors"]:
            self.assertIn("name", d)
            self.assertIn("score", d)
            self.assertIsInstance(d["regions"], list)
