"""Tests for Google Sheets criterion template parsing."""

import unittest

from app.internal.services.google_sheet_service import (
    GoogleSheetError,
    parse_sheet_rows,
    parse_spreadsheet_url,
    slugify,
)


class GoogleSheetParserTests(unittest.TestCase):
    def test_parse_spreadsheet_url_standard(self):
        url = "https://docs.google.com/spreadsheets/d/abc123XYZ-_/edit#gid=456"
        sid, gid = parse_spreadsheet_url(url)
        self.assertEqual(sid, "abc123XYZ-_")
        self.assertEqual(gid, "456")

    def test_parse_spreadsheet_url_direct_id(self):
        sid, gid = parse_spreadsheet_url("abc123XYZ-_abc123XYZ-_")
        self.assertEqual(sid, "abc123XYZ-_abc123XYZ-_")
        self.assertIsNone(gid)

    def test_parse_spreadsheet_url_invalid(self):
        with self.assertRaises(GoogleSheetError):
            parse_spreadsheet_url("https://example.com/not-a-sheet")

    def test_parse_sheet_rows_three_columns_with_header(self):
        rows = [
            ["Блок", "Критерий", "Тип"],
            ["Сервис", "Приветствие гостя", "да/нет"],
            ["", "Чистота зала", "балльная"],
            ["Кухня", "Сроки подачи", "число"],
        ]
        parsed = parse_sheet_rows(rows)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0].block, "Сервис")
        self.assertEqual(parsed[0].criterion, "Приветствие гостя")
        self.assertEqual(parsed[0].value_type, "boolean")
        self.assertEqual(parsed[1].value_type, "number")
        self.assertEqual(parsed[2].block, "Кухня")
        self.assertEqual(parsed[2].value_type, "number")

    def test_parse_sheet_rows_block_carry_forward(self):
        rows = [
            ["Сервис", "Критерий А", "bool"],
            ["", "Критерий Б", ""],
        ]
        parsed = parse_sheet_rows(rows)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[1].block, "Сервис")
        self.assertEqual(parsed[1].value_type, "boolean")

    def test_slugify_cyrillic(self):
        code = slugify("Блок №1")
        self.assertTrue(code)
        self.assertLessEqual(len(code), 80)


if __name__ == "__main__":
    unittest.main()
