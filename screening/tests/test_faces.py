import os

import cv2
from django.conf import settings
from django.test import TestCase

from screening import faces

A_DOC = settings.DEMO_ASSETS_DIR / "subject_a_passport_photo.jpg"
A_LIVE = settings.DEMO_ASSETS_DIR / "subject_a_live_capture.jpg"
B_DOC = settings.DEMO_ASSETS_DIR / "subject_b_passport_photo.jpg"


class FaceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not (os.path.exists(A_DOC) and os.path.exists(A_LIVE)
                and os.path.exists(B_DOC)):
            cls.skipTest(cls, "demo face assets missing")

    def test_detection_finds_portrait(self):
        img = cv2.imread(str(A_DOC))
        self.assertTrue(faces.detect_faces(img))

    def test_genuine_match(self):
        res = faces.verify(cv2.imread(str(A_DOC)), cv2.imread(str(A_LIVE)),
                           settings.SFACE_MATCH_THRESHOLD)
        self.assertTrue(res["matched"], res)
        self.assertGreater(res["similarity"], 0.5)

    def test_imposter_rejected(self):
        res = faces.verify(cv2.imread(str(A_DOC)), cv2.imread(str(B_DOC)),
                           settings.SFACE_MATCH_THRESHOLD)
        self.assertFalse(res["matched"], res)
