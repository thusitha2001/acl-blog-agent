from __future__ import annotations

import unittest

from acl_agent.validation import count_h1, normalize_single_h1


class NormalizeSingleH1Tests(unittest.TestCase):
    def test_inserts_title_when_body_has_no_h1(self):
        article = "<h2>Fabric</h2>\n<p>Choose linen for dinner.</p>"
        fixed = normalize_single_h1(article, "How to choose napkins")
        self.assertEqual(count_h1(fixed), 1)
        self.assertIn("<h1>How to choose napkins</h1>", fixed)

    def test_demotes_extra_markdown_h1s(self):
        article = (
            "# How to choose napkins\n\n"
            "# Fabric\n\n"
            "Choose linen.\n\n"
            "# Size\n"
        )
        fixed = normalize_single_h1(article, "How to choose napkins")
        self.assertEqual(count_h1(fixed), 1)
        self.assertIn("## Fabric", fixed)
        self.assertIn("## Size", fixed)

    def test_prefers_html_h1_and_demotes_markdown(self):
        article = (
            "<h1>How to choose napkins</h1>\n\n"
            "# Fabric\n\n"
            "<p>Choose linen.</p>"
        )
        fixed = normalize_single_h1(article, "How to choose napkins")
        self.assertEqual(count_h1(fixed), 1)
        self.assertIn("<h1>How to choose napkins</h1>", fixed)
        self.assertIn("## Fabric", fixed)

    def test_keeps_a_valid_single_h1(self):
        article = "<h1>How to choose napkins</h1>\n<p>Choose linen.</p>"
        fixed = normalize_single_h1(article, "How to choose napkins")
        self.assertEqual(fixed, article)


if __name__ == "__main__":
    unittest.main()
