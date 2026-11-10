import io
import unittest
from starlette.datastructures import UploadFile
from app.imports import read_csv,safe_csv

class ImportTests(unittest.TestCase):
    def test_export_prevents_spreadsheet_formula_execution(self):
        self.assertEqual(safe_csv('=SUM(1,2)'), "'=SUM(1,2)")
        self.assertEqual(safe_csv(' +cmd'), "' +cmd")
        self.assertEqual(safe_csv('@HYPERLINK(1)'), "'@HYPERLINK(1)")
        self.assertEqual(safe_csv('-125.50',numeric=True), '-125.50')
        self.assertEqual(safe_csv('-125.50'), "'-125.50")
        self.assertEqual(safe_csv('Normaltext'),'Normaltext')

    def test_import_recognizes_comma_and_cp1252(self):
        f=UploadFile(file=io.BytesIO('name,city\nJ\xfcrgen,Zuerich\n'.encode('latin-1')),
                     filename='kunden.csv')
        records=read_csv(f)
        self.assertEqual(records[0][1]['name'],'J\u00fcrgen')
        self.assertEqual(records[0][1]['city'],'Zuerich')

    def test_import_rejects_oversized_and_duplicate_headers(self):
        f=UploadFile(file=io.BytesIO(b'name;name\na;b\n'),filename='file.csv')
        with self.assertRaisesRegex(ValueError,'eindeutige'):read_csv(f)
        too_big=UploadFile(file=io.BytesIO(b'x'*(2_000_001)),filename='file.csv')
        with self.assertRaisesRegex(ValueError,'2 MB'):read_csv(too_big)
