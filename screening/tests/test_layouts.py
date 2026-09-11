"""End-to-end extraction tests against the synthetic Indian document layouts.

The corpus is generated once for the whole class (OCR is the slow part);
each test then asserts the field values the layouts are specified to carry.
"""
import shutil
import tempfile

import cv2
from django.test import TestCase

from screening import ocr_engine, synthetic
from screening.mrz import parse_mrz


class LayoutExtractionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dir = tempfile.mkdtemp(prefix="layout_tests_")
        cls.paths = synthetic.generate_demo_docs(cls.dir)
        cls.fields, cls.types, cls.mrzs = {}, {}, {}
        for key in ("clean_passport", "visa", "id_card", "license"):
            img = cv2.imread(cls.paths[key])
            fz = ocr_engine.extract_fields(img)
            cls.fields[key] = fz
            cls.types[key] = ocr_engine.classify_document(img, fz["raw_text"])
            mrz_lines, _ = ocr_engine.read_mrz(img)
            cls.mrzs[key] = parse_mrz(mrz_lines) if mrz_lines else None

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)
        super().tearDownClass()

    def _v(self, doc, field):
        return self.fields[doc]["values"].get(field)

    def test_passport_classification_and_fields(self):
        self.assertEqual(self.types["clean_passport"], "passport")
        self.assertEqual(self._v("clean_passport", "surname"), "SHARMA")
        self.assertEqual(self._v("clean_passport", "given_names"), "PRIYA")
        self.assertEqual(self._v("clean_passport", "doc_number"), "Z1234567")
        self.assertEqual(self._v("clean_passport", "nationality"), "IND")
        self.assertEqual(self._v("clean_passport", "dob"), "12-03-1995")
        self.assertEqual(self._v("clean_passport", "expiry"), "20-11-2031")
        self.assertEqual(self._v("clean_passport", "sex"), "F")
        self.assertEqual(self._v("clean_passport", "place_of_birth"), "DELHI, DELHI")
        self.assertEqual(self._v("clean_passport", "place_of_issue"), "DELHI")
        self.assertEqual(self._v("clean_passport", "date_of_issue"), "21-11-2021")

    def test_passport_mrz_checks_pass(self):
        mrz = self.mrzs["clean_passport"]
        self.assertIsNotNone(mrz)
        self.assertEqual(mrz["format"], "TD3")
        self.assertEqual(mrz["doc_number"], "Z1234567")
        self.assertTrue(all(mrz["checks"].values()), mrz["checks"])

    def test_visa_classification_and_fields(self):
        self.assertEqual(self.types["visa"], "visa")
        self.assertEqual(self._v("visa", "visa_number"), "V88012345")
        self.assertEqual(self._v("visa", "visa_type"), "BUSINESS")
        self.assertEqual(self._v("visa", "entries"), "MULTIPLE")

    def test_visa_mrv_b_mrz_supplies_validity(self):
        mrz = self.mrzs["visa"]
        self.assertIsNotNone(mrz)
        self.assertEqual(mrz["format"], "MRV-B")
        self.assertEqual(mrz["doc_number"], "V88012345")
        self.assertTrue(all(mrz["checks"].values()), mrz["checks"])

    def test_aadhaar_card_fields(self):
        self.assertEqual(self.types["id_card"], "id_card")
        self.assertEqual(self._v("id_card", "full_name"), "SHARMA PRIYA")
        self.assertEqual(self._v("id_card", "dob"), "12-03-1995")
        self.assertEqual(self._v("id_card", "sex"), "F")
        self.assertEqual(self._v("id_card", "aadhaar_number"), "8234 5671 9012")

    def test_driving_licence_fields(self):
        self.assertEqual(self.types["license"], "driving_license")
        # OCR may read the "0" as "O"; the O->0 normalisation must repair it
        self.assertEqual(self._v("license", "doc_number").replace("O", "0"),
                         "AN01 20130003278")
        self.assertEqual(self._v("license", "dob"), "20/12/1987")
        self.assertEqual(self._v("license", "date_of_issue"), "23/09/2013")
        self.assertIn("MOHAMMED ALI", self._v("license", "father_name"))
        self.assertNotIn("(Son of", self._v("license", "father_name"))
        self.assertEqual(self._v("license", "blood_group"), "A+")
