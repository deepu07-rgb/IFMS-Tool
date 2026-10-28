"""Short printed tables keep source geometry despite surrounding letter text."""

import unittest

import cv2
import numpy as np

from ifms_suite.statement_grid import extract_statement_grid


def letter_image():
    image = np.full((1200, 1000, 3), 255, np.uint8)
    for y in range(100, 650, 45):
        cv2.putText(
            image,
            "Office letter: requested statement and supporting records",
            (35, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 0, 0),
            1,
        )
    return image


class ShortStatementGridTests(unittest.TestCase):
    def test_embedded_short_grid_keeps_original_coordinates_and_raw_candidates(self):
        image = letter_image()
        for x in (40, 220, 400, 580, 760, 940):
            cv2.line(image, (x, 750), (x, 930), (50, 50, 50), 2)
        for y in (750, 810, 870, 930):
            cv2.line(image, (40, y), (940, y), (50, 50, 50), 2)
        cv2.putText(
            image, "7319", (65, 850), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2
        )
        result = extract_statement_grid(
            image,
            lambda *a, **k: ([["7319", 0.92]], None),
            source_sha256="short-source",
            page_number=2,
        )
        self.assertEqual(len(result["cells"]), 15)
        np.testing.assert_allclose(
            result["source_grid_polygon"],
            [[40, 750], [940, 750], [940, 930], [40, 930]],
            atol=4,
        )
        cell = next(c for c in result["cells"] if c["candidates"])
        self.assertEqual(cell["candidates"][0]["text"], "7319")
        self.assertIsNone(cell["amount"])
        self.assertEqual(cell["source_sha256"], "short-source")
        self.assertEqual(cell["source_page"], 2)
        self.assertGreater(
            min(p[1] for p in cell["candidates"][0]["source_polygon"]), 810
        )
        self.assertEqual(result["semantic_rows"], [])
        self.assertTrue(result["review_required"])

    def test_page_crease_crossing_short_table_does_not_create_a_column(self):
        image = letter_image()
        for x in (40, 220, 400, 580, 760, 940):
            cv2.line(image, (x, 750), (x, 930), (50, 50, 50), 2)
        for y in (750, 810, 870, 930):
            cv2.line(image, (40, y), (940, y), (50, 50, 50), 2)
        cv2.line(image, (490, 10), (490, 1190), (110, 110, 110), 1)
        result = extract_statement_grid(image)
        self.assertEqual(len(result["cells"]), 15)
        self.assertEqual(len(result["column_rules"]), 6)

    def test_plain_letter_and_disconnected_rule_noise_do_not_establish_grid(self):
        for noise in (False, True):
            image = letter_image()
            if noise:
                # Long baselines and separate vertical strokes do not intersect.
                for y in (750, 810, 870):
                    cv2.line(image, (40, y), (650, y), (0, 0, 0), 2)
                for x in (760, 840, 920):
                    cv2.line(image, (x, 740), (x, 950), (0, 0, 0), 2)
            result = extract_statement_grid(image)
            self.assertEqual(result["cells"], [])
            self.assertEqual(result["semantic_rows"], [])
            self.assertIn("Insufficient ruled-table grid evidence", result["issues"])
