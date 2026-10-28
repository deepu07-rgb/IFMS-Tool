"""Geometry and conservative literal extraction; no sample answers embedded."""

import unittest
import numpy as np
import cv2

from ifms_suite.statement_grid import (
    extract_statement_grid,
    literal_money,
    _mapped_rows,
)
from ifms_suite.due_drawn import parse_statement_table


def ruled_image(two_lines=False):
    image = np.full((340, 480, 3), 255, np.uint8)
    for x in (40, 160, 280, 420):
        cv2.line(image, (x, 40), (x, 290), (50, 50, 50), 2)
    for y in (40, 120, 200, 290):
        cv2.line(image, (40, y), (420, y), (50, 50, 50), 2)
    cv2.putText(image, "1234", (65, 76), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2)
    if two_lines:
        cv2.putText(
            image, "1234", (65, 108), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2
        )
    return image


class LiteralMoneyTests(unittest.TestCase):
    def test_only_complete_literal_numeric_tokens(self):
        for text, value in [
            ("1,234.50", "1234.50"),
            ("1,23,456", "123456"),
            ("0", "0"),
        ]:
            self.assertEqual(literal_money(text), value)
        for text in (
            "",
            "-",
            "O",
            "I234",
            "1234 567",
            "1,23",
            "123/-",
            "1e3",
            "NaN",
            "-20",
        ):
            self.assertIsNone(literal_money(text))


class StatementGridTests(unittest.TestCase):
    def test_clipped_right_border_preserves_unassigned_source_candidates(self):
        image = np.full((340, 480, 3), 255, np.uint8)
        for x in (40, 160, 280):
            cv2.line(image, (x, 40), (x, 290), (50, 50, 50), 2)
        for y in (40, 120, 200, 290):
            cv2.line(image, (40, y), (479, y), (50, 50, 50), 2)
        cv2.putText(
            image, "7319", (320, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2
        )
        result = extract_statement_grid(image, lambda *a, **k: ([["7319", 0.99]], None))
        self.assertEqual(len(result["cells"]), 6)
        self.assertTrue(result.get("source_margin_regions"))
        margin = result["source_margin_regions"][0]
        self.assertEqual(margin["candidates"][0]["text"], "7319")
        self.assertIsNone(margin["column"])
        self.assertIsNone(margin["text"])
        self.assertIsNone(margin["amount"])
        self.assertEqual(margin["status"], "source_geometry_unresolved")
        self.assertTrue(margin["review_required"])
        self.assertLessEqual(max(p[0] for p in margin["source_polygon"]), 479)
        self.assertNotIn("7319", [v for row in result["table_rows"] for v in row])
        self.assertEqual(result["semantic_rows"], [])

    def test_faded_rules_keep_first_content_inside_source_grid(self):
        image = np.full((340, 480, 3), 255, np.uint8)
        for x in (40, 160, 280, 420):
            cv2.line(image, (x, 40), (x, 290), (240, 240, 240), 1)
        for y in (40, 120, 200, 290):
            cv2.line(image, (40, y), (420, y), (240, 240, 240), 1)
        cv2.putText(
            image, "1234", (65, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2
        )
        result = extract_statement_grid(image)
        self.assertEqual(len(result["cells"]), 9)
        self.assertLess(abs(result["source_grid_polygon"][0][1] - 40), 3)
        self.assertEqual(result["cells"][0]["row"], 0)
        self.assertIsNone(result["cells"][0]["amount"])

    def test_real_rules_define_cells_and_provenance(self):
        calls = []

        def recognize(image, **kwargs):
            calls.append(kwargs)
            return [["1234", 0.99]], None

        result = extract_statement_grid(
            ruled_image(), recognize, source_sha256="abc", page_number=4
        )
        self.assertEqual(len(result["column_rules"]), 4)
        self.assertEqual(len(result["row_rules"]), 4)
        self.assertEqual(len(result["cells"]), 9)
        self.assertTrue(result["review_required"])
        self.assertEqual(result["source_margin_regions"], [])
        self.assertEqual(result["cells"][0]["amount"], "1234")
        self.assertEqual(result["cells"][0]["source_sha256"], "abc")
        self.assertEqual(result["cells"][0]["source_page"], 4)
        self.assertEqual(len(result["cells"][0]["source_polygon"]), 4)
        self.assertTrue(all(c == {"use_det": False, "use_cls": False} for c in calls))
        self.assertIsNone(result["cells"][-1]["amount"])
        self.assertEqual(result["semantic_rows"], [])
        self.assertTrue(any("Unknown" in issue for issue in result["issues"]))

    def test_perspective_geometry_uses_observed_rules(self):
        original = ruled_image()
        source = np.float32([[40, 40], [420, 40], [420, 290], [40, 290]])
        target = np.float32([[55, 30], [423, 55], [405, 300], [30, 275]])
        transform = cv2.getPerspectiveTransform(source, target)
        image = cv2.warpPerspective(
            original, transform, (480, 340), borderValue=(255, 255, 255)
        )
        result = extract_statement_grid(image)
        self.assertEqual(len(result["column_rules"]), 4)
        self.assertEqual(len(result["row_rules"]), 4)
        self.assertEqual(len(result["cells"]), 9)
        self.assertLess(
            np.max(
                np.linalg.norm(np.array(result["source_grid_polygon"]) - target, axis=1)
            ),
            8,
        )

    def test_multiple_baselines_never_become_one_financial_value(self):
        def recognize(image, **kwargs):
            return [["1234", 0.99]], None

        result = extract_statement_grid(ruled_image(True), recognize)
        cell = result["cells"][0]
        self.assertEqual(cell["status"], "ambiguous_multiple_lines")
        self.assertIsNone(cell["text"])
        self.assertIsNone(cell["amount"])
        self.assertEqual(len(cell["candidates"]), 2)
        self.assertEqual([c["line_index"] for c in cell["candidates"]], [0, 1])

    def test_missing_grid_and_low_confidence_do_not_create_rows(self):
        result = extract_statement_grid(np.full((340, 480, 3), 255, np.uint8))
        self.assertEqual(result["cells"], [])
        self.assertEqual(result["semantic_rows"], [])
        result = extract_statement_grid(
            ruled_image(), lambda *a, **k: ([["999", 0.92]], None)
        )
        self.assertIsNone(result["cells"][0]["amount"])
        with self.assertRaises(ValueError):
            extract_statement_grid(ruled_image(), minimum_confidence=0.8)

    def test_explicit_mapping_only_labels_values_and_preserves_missing(self):
        mapping = {
            "month_column": 0,
            "groups": {
                "due": {"Basic": 1, "Total": 2},
                "drawn": {"Basic": 3, "Total": 4},
            },
        }
        rows = _mapped_rows([["Jul-2026", "120", "120", None, "100"]], mapping)
        parsed = parse_statement_table(rows)
        self.assertEqual(len(parsed), 1)
        self.assertIsNone(parsed[0]["drawn"]["Basic"])
        self.assertEqual(str(parsed[0]["due"]["Basic"]), "120.00")
        self.assertTrue(parsed[0]["issues"])
        with self.assertRaises(ValueError):
            _mapped_rows(
                [["Jul-2026", 1, 2, 3, 4]],
                {
                    "month_column": 0,
                    "groups": {
                        "due": {"Basic": 1, "Total": 2},
                        "drawn": {"Basic": 1, "Total": 4},
                    },
                },
            )


if __name__ == "__main__":
    unittest.main()
