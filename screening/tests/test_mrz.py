from datetime import date

from django.test import TestCase

from screening.mrz import (build_mrv_b, build_td3, compute_checksum, parse_mrz,
                           parse_mrv_b, parse_td3, resolve_yymmdd)


class MrzTests(TestCase):
    def test_checksum_known_vector(self):
        # ICAO 9303 weights 7,3,1: 'Z1234567<' -> documented example behaviour
        self.assertEqual(compute_checksum("Z1234567<"), 1)
        self.assertEqual(compute_checksum("950312"), 4)

    def test_roundtrip_td3(self):
        l1, l2 = build_td3("P", "IND", "SHARMA", "PRIYA", "Z1234567", "IND",
                           date(1995, 3, 12), date(2031, 11, 20), "F")
        self.assertEqual(len(l1), 44)
        self.assertEqual(len(l2), 44)
        p = parse_mrz([l1, l2])
        self.assertTrue(all(p["checks"].values()))
        self.assertEqual(p["doc_number"], "Z1234567")
        self.assertEqual(p["surname"], "SHARMA")
        self.assertEqual(p["given_names"], "PRIYA")
        self.assertEqual(p["dob"]["date"], date(1995, 3, 12))
        self.assertEqual(p["expiry"]["date"], date(2031, 11, 20))
        self.assertEqual(p["sex"], "F")

    def test_ocr_correction(self):
        l1, l2 = build_td3("P", "IND", "SHARMA", "PRIYA", "Z1234567", "IND",
                           date(1995, 3, 12), date(2031, 11, 20), "F")
        corrupted = "2" + l2[1:]          # Z misread as 2
        p = parse_td3(l1, corrupted)
        self.assertEqual(p["doc_number"], "Z1234567")
        self.assertTrue(p["checks"]["doc_number"])
        self.assertTrue(p["ocr_fixes"])

    def test_roundtrip_mrv_b(self):
        # Type-B visa MRZ (2x36) used on the demo visa sticker
        l1, l2 = build_mrv_b("V88012345", "IND", "SHARMA", "PRIYA", "IND",
                             date(1995, 3, 12), date(2031, 11, 20), "F")
        self.assertEqual(len(l1), 36)
        self.assertEqual(len(l2), 36)
        p = parse_mrz([l1, l2])          # auto-detection must pick MRV-B
        self.assertEqual(p["format"], "MRV-B")
        self.assertTrue(all(p["checks"].values()))
        self.assertEqual(p["doc_number"], "V88012345")
        self.assertEqual(p["surname"], "SHARMA")
        self.assertEqual(p["given_names"], "PRIYA")
        self.assertEqual(p["sex"], "F")
        self.assertEqual(p["dob"]["date"], date(1995, 3, 12))
        self.assertEqual(p["expiry"]["date"], date(2031, 11, 20))

    def test_mrv_b_ocr_correction(self):
        l1, l2 = build_mrv_b("V88012345", "IND", "SHARMA", "PRIYA", "IND",
                             date(1995, 3, 12), date(2031, 11, 20), "F")
        corrupted = l2[:2] + "B" + l2[3:]  # second 8 misread as B
        p = parse_mrv_b(l1, corrupted)
        self.assertEqual(p["doc_number"], "V88012345")
        self.assertTrue(p["checks"]["visa_number"])
        self.assertTrue(p["ocr_fixes"])

    def test_century_resolution(self):
        self.assertEqual(resolve_yymmdd("950312", "dob")["date"].year, 1995)
        self.assertGreaterEqual(resolve_yymmdd("311120", "expiry")["date"].year, 2031)
