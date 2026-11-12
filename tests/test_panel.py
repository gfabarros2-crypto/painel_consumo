import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from domain import analyze, classify, normalize_record, shift_month  # noqa: E402
from extractor import parse_pdf, parse_row_line  # noqa: E402
import server  # noqa: E402


def entry(period, consumption, resource="water"):
    return normalize_record({
        "resource": resource, "period": period, "consumption": consumption,
        "total_brl": 0, "source_url": "", "receipt_url": "", "receipt_approved": False,
    })


class DomainTests(unittest.TestCase):
    def test_six_calendar_months_cross_year(self):
        records = [entry(period, value) for period, value in zip(
            ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04"],
            [10, 20, 30, 40, 50, 60, 70],
        )]
        result = analyze(records, "water", "2026-04")
        self.assertEqual([x["period"] for x in result["history"]], [
            "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"
        ])
        self.assertEqual(result["average"], 35)
        self.assertEqual(result["variation_percent"], 100)
        self.assertEqual(shift_month("2026-01", -1), "2025-12")

    def test_missing_month_differs_from_recorded_zero(self):
        periods = ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"]
        records = [entry(period, 0) for period in periods] + [entry("2026-04", 10)]
        zero_history = analyze(records, "water", "2026-04")
        self.assertEqual(zero_history["average"], 0)
        self.assertIsNone(zero_history["variation_percent"])
        incomplete = analyze(records[1:], "water", "2026-04")
        self.assertIsNone(incomplete["average"])
        self.assertIn("Faltam valores de consumo", incomplete["comparison_reason"])

    def test_invoice_without_kwh_is_not_zero_consumption(self):
        invoice = normalize_record({
            "resource": "energy", "period": "2022-09", "consumption": None,
            "consumption_missing_confirmed": True, "total_brl": 97421.94,
        })
        result = analyze([invoice], "energy", "2022-09")
        self.assertIsNone(result["selected"]["consumption"])
        self.assertEqual(result["selected"]["total_brl"], 97421.94)
        self.assertIsNone(result["variation_percent"])
        self.assertEqual(result["status"]["code"], "unavailable")
        with self.assertRaises(ValueError):
            normalize_record({"resource": "energy", "period": "2022-09", "consumption": None, "total_brl": 97421.94})

    def test_literal_legal_boundaries_are_not_guessed(self):
        average = Decimal("100")
        checks = [
            ("99.99", "conscious"), ("100", "adequate"), ("110", "adequate"),
            ("110.5", "pending"), ("111", "alert"), ("149.99", "alert"),
            ("150", "pending"), ("150.01", "abusive"),
        ]
        for value, expected in checks:
            with self.subTest(value=value):
                self.assertEqual(classify(Decimal(value), average)["code"], expected)

    def test_absent_receipt_does_not_require_link(self):
        row = entry("2026-04", 0)
        self.assertFalse(row["receipt_approved"])
        self.assertIsNone(row["receipt_url"])
        with self.assertRaises(ValueError):
            normalize_record({**row, "receipt_approved": True})


class ExtractorTests(unittest.TestCase):
    def test_official_energy_pdf_preserves_blank_kwh(self):
        pdf = (ROOT / "public" / "planilhas" / "energia-empetur-2022.pdf").read_bytes()
        result = parse_pdf(pdf, "energy")
        self.assertEqual(len(result["rows"]), 9)
        self.assertEqual(result["rows"][0]["period"], "2022-01")
        self.assertIsNone(result["rows"][0]["consumption"])
        self.assertEqual(result["rows"][0]["total_brl"], 113012.63)
        self.assertEqual(result["rows"][-1]["total_brl"], 97421.94)
        self.assertTrue(result["rows"][-1]["needs_review"])

    def test_ambiguous_multiple_money_columns_require_correction(self):
        row = parse_row_line("set.-26 120 R$ 800,00 R$ 400,00 R$ 1.200,00", "water")
        self.assertEqual(row["consumption"], 120)
        self.assertIsNone(row["total_brl"])
        self.assertTrue(row["needs_review"])

    def test_official_water_pdf_rows(self):
        pdf = (ROOT / "public" / "planilhas" / "agua-empetur-2022.pdf").read_bytes()
        result = parse_pdf(pdf, "water")
        self.assertEqual(len(result["rows"]), 9)
        self.assertEqual(result["rows"][0]["period"], "2022-01")
        self.assertEqual(result["rows"][0]["consumption"], 5839)
        self.assertEqual(result["rows"][-1]["period"], "2022-09")
        self.assertEqual(result["rows"][-1]["total_brl"], 66017.23)
        self.assertFalse(result["warnings"])


class StorageTests(unittest.TestCase):
    def test_private_blob_keeps_updates_and_imports(self):
        class FakeBlob:
            def __init__(self):
                self.objects = {}

            def get(self, pathname, *, access):
                self.assert_private(access)
                content = self.objects.get(pathname)
                return SimpleNamespace(status_code=200, stream=[content]) if content is not None else None

            def put(self, pathname, content, *, access, **options):
                self.assert_private(access)
                self.objects[pathname] = content

            @staticmethod
            def assert_private(access):
                assert access == "private"

        blob = FakeBlob()
        with patch.object(server, "blob_client", return_value=blob):
            data = server.read_data()
            self.assertEqual(len(data["records"]), 18)
            data["last_updated"] = "2026-11-12T00:00:00+00:00"
            server.save_data(data)
            self.assertEqual(server.read_data()["last_updated"], data["last_updated"])
            server.save_import("a" * 32, b"%PDF-test")
            self.assertTrue(server.import_exists("a" * 32))
            self.assertTrue(any(key.endswith(".pdf") for key in blob.objects))


if __name__ == "__main__":
    unittest.main()
