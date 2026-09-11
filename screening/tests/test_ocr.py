import os
from unittest import mock

from django.test import TestCase

from screening import ocr_engine


class TesseractConfigTests(TestCase):
    def setUp(self):
        self._saved_cmd = ocr_engine.pytesseract.pytesseract.tesseract_cmd

    def tearDown(self):
        ocr_engine.pytesseract.pytesseract.tesseract_cmd = self._saved_cmd

    def test_windows_default_install_detected(self):
        win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        with mock.patch.object(ocr_engine.sys, "platform", "win32"), \
             mock.patch.object(ocr_engine.shutil, "which", return_value=None), \
             mock.patch.object(ocr_engine.os.path, "exists",
                               side_effect=lambda p: p == win):
            chosen = ocr_engine._configure_tesseract()
        self.assertEqual(chosen, win)
        self.assertEqual(ocr_engine.pytesseract.pytesseract.tesseract_cmd, win)

    def test_env_var_wins(self):
        with mock.patch.object(ocr_engine.shutil, "which", return_value=None), \
             mock.patch.dict(os.environ, {"TESSERACT_CMD": "/opt/tess"}), \
             mock.patch.object(ocr_engine.os.path, "exists",
                               side_effect=lambda p: p == "/opt/tess"):
            chosen = ocr_engine._configure_tesseract()
        self.assertEqual(chosen, "/opt/tess")

    def test_on_path_means_no_override(self):
        with mock.patch.object(ocr_engine.shutil, "which",
                               return_value="/usr/bin/tesseract"):
            self.assertIsNone(ocr_engine._configure_tesseract())
