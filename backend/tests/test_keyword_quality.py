"""Regression tests for keyword validation, intent, AIO/SXO, and content gaps."""
from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from acl_agent.analysis_input import average_competitor_scores
from acl_agent.analysis_report import action_plan, content_gaps, originality_report
from acl_agent.competitors import _score_page
from acl_agent.auto_brief import SERPResult, extract_nlp_keywords
from acl_agent.keywords import (
    classify_page_intent,
    compare_keywords,
    domain_nouns,
    extract_terms,
    fold_accents,
    is_closing_section,
    is_search_phrase,
    keyword_focus,
    match_status,
    search_phrase_check,
    noun_chunk_phrases,
    phrase_key,
    phrase_segments,
    validate_keyword,
)


HOODIE_ARTICLE = (
    "How to Style Men’s Oversized Hoodies: Best Outfit Ideas. "
    "An oversized hoodie looks better when the shoulders sit slightly past your own "
    "and the hem hits mid-hip. Pair it with tapered jeans, clean sneakers, and a "
    "simple watch. Layer a chore coat over the hoodie in cold weather. "
    "Casual streetwear looks work when you keep one item fitted. "
    "Avoid stacking baggy pants with a huge hoodie. "
    "Choose a color that contrasts with your denim. "
) * 4

HOODIE_PAGE = {
    "title": "How to Style Men’s Oversized Hoodies: Best Outfit Ideas",
    "h1": "How to Style Men’s Oversized Hoodies: Best Outfit Ideas",
    "h1_headings": ["How to Style Men’s Oversized Hoodies: Best Outfit Ideas"],
    "h2_headings": ["Casual streetwear looks", "Layering in cold weather"],
    "text": HOODIE_ARTICLE,
    "full_text": HOODIE_ARTICLE,
    "meta_description": "Outfit ideas for styling oversized hoodies.",
    "extract_ok": True,
    "word_count": len(HOODIE_ARTICLE.split()),
    "source_markdown": "# How to Style Men’s Oversized Hoodies\n\n" + HOODIE_ARTICLE,
    "schema_types": ["Article"],
    "author": "Editor",
    "faq": {"answered": 0},
    "domain": "example.com",
    "url": "https://example.com/style-mens-oversized-hoodies",
    "content_type": "Blog",
}

SHOP_COMPETITORS = [
    {
        "title": "Buy Oversized Shirts for Men Online in India",
        "url": "https://www.bewakoof.com/collections/oversized-t-shirts",
        "domain": "bewakoof.com",
        "h1_headings": ["Buy Oversized Shirts for Men Online in India"],
        "h2_headings": ["Size chart", "Add to cart"],
        "text": "Buy oversized shirts for men online. Best prices on oversized t shirt men.",
        "snippet": "Shop oversized t-shirts",
        "meta_description": "Buy oversized t-shirts for men and women online.",
    },
    {
        "title": "Buy Oversized T-shirts For Men & Women Online | Bewakoof",
        "url": "https://www.bewakoof.com/oversized-t-shirts",
        "domain": "bewakoof.com",
        "h2_headings": [],
        "text": "Bewakoof oversized t shirt collection.",
    },
    {
        "title": "Buy Oversized & Baggy T-Shirts for Men Online in India | Trendy Streetwear – CrazyMonk",
        "url": "https://crazymonk.in/collections/oversized",
        "domain": "crazymonk.in",
        "h2_headings": [],
        "text": "CrazyMonk baggy t-shirts.",
    },
    {
        "title": "Amazon.in : oversized",
        "url": "https://www.amazon.in/s?k=oversized",
        "domain": "amazon.in",
        "h2_headings": [],
        "text": "Amazon oversized products.",
    },
    {
        "title": "Oversized T Shirt Men",
        "url": "https://shop.example/oversized-t-shirt-men",
        "domain": "shop.example",
        "h2_headings": ["Buy now"],
        "text": "Buy oversized t shirt men online.",
    },
]

GUIDE_COMPETITOR = {
    "title": "Oversized hoodie outfit guide",
    "url": "https://style.example/oversized-hoodie-outfits",
    "domain": "style.example",
    "h1_headings": ["Oversized hoodie outfit guide"],
    "h2_headings": [
        "How should an oversized hoodie fit?",
        "What pants pair well with an oversized hoodie?",
        "Best shoes for an oversized hoodie outfit",
    ],
    "text": (
        "How should an oversized hoodie fit? The shoulder seam should sit just past yours. "
        "What pants pair well with an oversized hoodie? Tapered jeans keep the look balanced. "
        "Best shoes for an oversized hoodie outfit are chunky sneakers. "
        "Layering oversized hoodies with jackets works in winter."
    ),
    "snippet": "A styling guide for oversized hoodie outfits.",
}


class TitleNotKeywordTests(unittest.TestCase):
    def test_page_titles_are_not_returned_as_keywords(self):
        report = compare_keywords("style mens oversized hoodies", HOODIE_PAGE, SHOP_COMPETITORS)
        phrases = [row["keyword"].lower() for row in report["table"]]
        banned = [
            "buy oversized shirts for men online in india",
            "oversized t shirt men",
            "buy oversized t-shirts for men & women online | bewakoof",
            "amazon.in : oversized",
            "buy oversized & baggy t-shirts",
        ]
        for phrase in banned:
            self.assertFalse(any(phrase in item for item in phrases), phrase)
        self.assertTrue(all(row.get("page_title_signal") is not True or row["type"] == "primary" for row in report["table"]))

    def test_brand_names_are_filtered(self):
        flags = validate_keyword(
            "Bewakoof oversized",
            "style mens oversized hoodies",
            source="heading",
            domains=["bewakoof.com"],
        )
        self.assertFalse(flags["accepted"])
        self.assertEqual(flags["rejection_reason"], "brand_or_domain")

    def test_product_titles_are_not_recommended_headings(self):
        gaps = content_gaps(HOODIE_PAGE, SHOP_COMPETITORS + [GUIDE_COMPETITOR], "style mens oversized hoodies")
        blob = " ".join(
            [row["missing_topic"] for row in gaps["table"]]
            + gaps["recommended_outline"]
            + [row["recommended_heading"] for row in gaps["table"]]
        ).lower()
        self.assertNotIn("bewakoof", blob)
        self.assertNotIn("crazymonk", blob)
        self.assertNotIn("amazon.in", blob)
        self.assertNotIn("buy oversized shirts", blob)
        self.assertTrue(any("pants" in row["missing_topic"].lower() or "fit" in row["missing_topic"].lower() for row in gaps["table"]))


class MatchStatusTests(unittest.TestCase):
    def test_close_variant_for_natural_title(self):
        match = match_status(
            "style mens oversized hoodies",
            HOODIE_ARTICLE,
            title=HOODIE_PAGE["title"],
            headings=HOODIE_PAGE["h2_headings"],
        )
        self.assertEqual(match["status"], "close_variant")
        self.assertIn("Oversized", match["matched_text"])
        self.assertIn("natural word-order", match["match_reason"])

    def test_exact_close_variant_and_missing(self):
        exact = match_status(
            "casual streetwear looks",
            HOODIE_ARTICLE,
            title=HOODIE_PAGE["title"],
            headings=HOODIE_PAGE["h2_headings"],
        )
        missing = match_status(
            "waterproof hiking boots",
            HOODIE_ARTICLE,
            title=HOODIE_PAGE["title"],
            headings=HOODIE_PAGE["h2_headings"],
        )
        report = compare_keywords("style mens oversized hoodies", HOODIE_PAGE, [GUIDE_COMPETITOR])
        primary = next(row for row in report["table"] if row["type"] == "primary")
        self.assertEqual(exact["status"], "exact")
        self.assertEqual(primary["my_blog_status"], "close_variant")
        self.assertEqual(missing["status"], "missing")
        self.assertIn(primary["my_blog_status"], {"exact", "close_variant", "missing"})


class IntentTests(unittest.TestCase):
    def test_shopping_pages_are_intent_mismatch(self):
        self.assertEqual(classify_page_intent(SHOP_COMPETITORS[0]), "transactional")
        self.assertEqual(classify_page_intent(GUIDE_COMPETITOR), "informational")
        report = compare_keywords("style mens oversized hoodies", HOODIE_PAGE, SHOP_COMPETITORS + [GUIDE_COMPETITOR])
        phrases = [row["keyword"].lower() for row in report["table"]]
        self.assertFalse(any("buy oversized" in item for item in phrases))


class ScoreAndPlanTests(unittest.TestCase):
    def test_aio_and_sxo_when_article_text_exists(self):
        scores = _score_page("style mens oversized hoodies", HOODIE_PAGE)
        self.assertIsInstance(scores["aio"], int)
        self.assertIsInstance(scores["sxo"], int)
        self.assertEqual(scores["reports"]["aio"]["status"], "available")
        self.assertEqual(scores["reports"]["sxo"]["status"], "available")
        self.assertTrue(scores["reports"]["aio"]["factors"])
        self.assertTrue(scores["reports"]["sxo"]["factors"])
        names = {f["name"] for f in scores["reports"]["aio"]["factors"]}
        self.assertIn("Entity clarity", names)
        sxo_names = {f["name"] for f in scores["reports"]["sxo"]["factors"]}
        self.assertIn("Search intent match", sxo_names)

    def test_null_aio_sxo_do_not_break_averages(self):
        rows = [
            {"scores": {"seo": 20, "geo": 50, "aeo": 40, "aio": None, "sxo": None}},
            {"scores": {"seo": 30, "geo": 60, "aeo": 50, "aio": None, "sxo": None}},
        ]
        avg = average_competitor_scores(rows)
        self.assertEqual(avg["seo"], 25.0)
        self.assertIsNone(avg["aio"])
        self.assertIsNone(avg["sxo"])

    def test_action_plan_from_real_findings(self):
        keywords = compare_keywords("style mens oversized hoodies", HOODIE_PAGE, [GUIDE_COMPETITOR])
        gaps = content_gaps(HOODIE_PAGE, [GUIDE_COMPETITOR], "style mens oversized hoodies")
        scores = _score_page("style mens oversized hoodies", HOODIE_PAGE)
        plan = action_plan(HOODIE_PAGE, scores, keywords, gaps, {"score": 70})
        self.assertTrue(plan)
        self.assertTrue(any(item["category"] in {"Keyword", "Content", "AEO"} for item in plan))

    def test_independent_reports_exist(self):
        original = originality_report(HOODIE_PAGE, [GUIDE_COMPETITOR])
        self.assertIn("Internal similarity check only", original["disclaimer"])
        self.assertIn("Not a definitive legal plagiarism determination", original["disclaimer"])
        gaps = content_gaps(HOODIE_PAGE, [GUIDE_COMPETITOR], "style mens oversized hoodies")
        self.assertTrue(gaps["recommended_outline"])
        self.assertTrue(any("fit" in h.lower() or "pants" in h.lower() or "faq" in h.lower() for h in gaps["recommended_outline"]))


PLACEMAT_TITLE = "Different Types of Placemats With a Tablecloth"
PLACEMAT_KEYWORD = "different types placemats tablecloth"
BAD_FRAGMENTS = [
    "many different",
    "come different",
    "tablecloths great",
    "tablecloths come",
    "placemats may",
    "get tablecloth",
    "kind tablecloth",
    "placemats feature",
    "replace tablecloths",
    "placemats add",
    "pair tablecloth",
    "different types",
]
GOOD_PHRASES = [
    "leather placemats",
    "cork placemats",
    "velvet placemats",
    "placemat sizes",
    "oval tablecloths",
    "denim placemats",
    "placemats for kids",
    "types of tablecloths",
    "heat damage",
    "kids table",
]
PLACEMAT_TEXT = (
    "Tablecloths come in many different materials. Tablecloths are great for "
    "formal dinners. Placemats may protect the table from heat. Leather placemats "
    "wipe clean. Cork placemats absorb heat. Velvet placemats feel rich. Denim "
    "placemats suit casual tables. Oval tablecloths fit oval tables. Check placemat "
    "sizes before you buy. What kind of tablecloth should you get? "
) * 2


class PhraseQualityTests(unittest.TestCase):
    def test_filter_rejects_fragments_and_keeps_noun_phrases(self):
        for nouns in (domain_nouns(PLACEMAT_TITLE, PLACEMAT_KEYWORD), set()):
            for phrase in BAD_FRAGMENTS:
                self.assertFalse(is_search_phrase(phrase, nouns), phrase)
            for phrase in GOOD_PHRASES:
                self.assertTrue(is_search_phrase(phrase, nouns), phrase)

    def test_extract_terms_stays_inside_sentences(self):
        terms = extract_terms(
            PLACEMAT_TEXT,
            ["Leather Placemats", "Cork Placemats"],
            PLACEMAT_KEYWORD,
            page_title=PLACEMAT_TITLE,
            page_relevance=0.5,
        )
        found = {term["keyword"] for term in terms}
        for phrase in BAD_FRAGMENTS + ["materials tablecloths", "dinners placemats"]:
            self.assertNotIn(phrase, found)
        self.assertIn("leather placemats", found)
        self.assertIn("cork placemats", found)

    def test_word_order_variants_collapse(self):
        self.assertEqual(phrase_key("come different"), phrase_key("different come"))
        terms = extract_terms(
            "Placemat sizes matter. Sizes placemat charts differ. Placemat sizes vary.",
            ["Placemat Sizes"],
            PLACEMAT_KEYWORD,
            page_title=PLACEMAT_TITLE,
            page_relevance=0.5,
        )
        keys = [phrase_key(term["keyword"]) for term in terms]
        self.assertEqual(len(keys), len(set(keys)))

    def test_compare_keywords_table_has_no_fragments(self):
        page = {
            "title": PLACEMAT_TITLE,
            "h1": PLACEMAT_TITLE,
            "h2_headings": ["Wooden Placemats", "Fabric Tablecloths"],
            "text": "Wooden placemats last. Fabric tablecloths soften a table.",
            "full_text": "Wooden placemats last. Fabric tablecloths soften a table.",
            "url": "https://example.com/different-types-of-placemats-with-a-tablecloth",
        }
        competitor = {
            "title": "Types of Placemats",
            "url": "https://guide.example/types-of-placemats",
            "domain": "guide.example",
            "h2_headings": ["Leather Placemats", "Cork Placemats", "Placemat Sizes"],
            "text": PLACEMAT_TEXT,
            "full_text": PLACEMAT_TEXT,
        }
        report = compare_keywords(
            PLACEMAT_KEYWORD,
            page,
            [competitor],
            serp_phrases=["tablecloths come", "many different", "oval tablecloths"],
        )
        found = {row["keyword"] for row in report["table"]}
        for phrase in BAD_FRAGMENTS:
            self.assertNotIn(phrase, found)
        self.assertIn("leather placemats", found)

    def test_serp_bigrams_use_same_filter(self):
        results = [
            SERPResult(
                "Types of Placemats",
                "https://guide.example/placemats",
                "Tablecloths come in many different materials. Leather placemats wipe clean.",
            ),
            SERPResult(
                "Placemat guide",
                "https://other.example/placemats",
                "Tablecloths are great. Leather placemats resist heat.",
            ),
        ]
        keywords = extract_nlp_keywords(PLACEMAT_KEYWORD, results)
        bigrams = [item for item in keywords if " " in item]
        for phrase in BAD_FRAGMENTS:
            self.assertNotIn(phrase, bigrams)
        self.assertIn("leather placemats", bigrams)


APPLIQUE_TITLE = "Appliqué vs Embroidery: Know the Difference"
APPLIQUE_KEYWORD = "applique embroidery know difference"
APPLIQUE_BAD = [
    "regarding embroidery",
    "passionate embroidery",
    "favorite pinterest",
    "favorite pinterest board",
    "combining appliqu",
    "combining appliqué",
    "realm of fabric",
    "digitizing matters",
    "defining appliqu",
    "defining appliqué",
    "art of combining",
    "weaving threads of creativity",
    "exploring embroidery",
    "ultimate guide",
    "quilting journey",
    "journey awaits",
    "vs embroidery",
    "both embroidery",
]
APPLIQUE_GOOD = [
    "applique vs embroidery",
    "embroidery digitizing",
    "embroidery stitches",
    "applique fabric",
    "stitch count",
    "cons of embroidery",
    "embroidery thread",
    "machine embroidery",
]
APPLIQUE_TEXT = (
    "Appliqué vs embroidery is a common question regarding embroidery projects. "
    "Combining appliqué with machine embroidery adds texture. Defining appliqué is simple: "
    "fabric shapes are stitched onto a base. Embroidery digitizing matters for stitch count. "
    "Weaving threads of creativity, the realm of fabric art awaits. "
    "Save it to your favorite Pinterest board. "
) * 2


class AppliqueFixtureTests(unittest.TestCase):
    def test_accents_fold_instead_of_truncating(self):
        self.assertEqual(fold_accents("appliqué"), "applique")
        self.assertEqual(phrase_segments("Combining appliqué"), [["combining", "applique"]])
        self.assertEqual(phrase_key("appliqué fabric"), phrase_key("applique fabric"))

    def test_filter_rejects_applique_garbage_and_keeps_good(self):
        for nouns in (domain_nouns(APPLIQUE_TITLE, APPLIQUE_KEYWORD), set()):
            for phrase in APPLIQUE_BAD:
                self.assertFalse(is_search_phrase(phrase, nouns), phrase)
            for phrase in APPLIQUE_GOOD:
                self.assertTrue(is_search_phrase(phrase, nouns), phrase)

    def test_social_platform_phrases_rejected(self):
        flags = validate_keyword("pinterest board", APPLIQUE_KEYWORD, source="body", page_relevance=0.5)
        self.assertFalse(flags["accepted"])
        self.assertEqual(flags["rejection_reason"], "brand_or_domain")

    def test_your_page_keyword_fields_are_clean(self):
        page = {
            "title": APPLIQUE_TITLE,
            "h1": APPLIQUE_TITLE,
            "h2_headings": ["Defining Appliqué", "The Art of Combining Appliqué and Embroidery"],
            "text": APPLIQUE_TEXT,
            "full_text": APPLIQUE_TEXT,
            "url": "https://example.com/applique-vs-embroidery-know-the-difference",
        }
        competitor = {
            "title": "Embroidery vs Appliqué",
            "url": "https://guide.example/embroidery-vs-applique",
            "domain": "guide.example",
            "h2_headings": ["Embroidery Stitches", "Appliqué Fabric"],
            "text": APPLIQUE_TEXT + " Embroidery stitches and appliqué fabric differ.",
            "full_text": APPLIQUE_TEXT + " Embroidery stitches and appliqué fabric differ.",
        }
        report = compare_keywords(APPLIQUE_KEYWORD, page, [competitor])
        found = {row["keyword"] for row in report["table"]}
        for phrase in APPLIQUE_BAD + ["pinterest board"]:
            self.assertNotIn(fold_accents(phrase), found)
        self.assertFalse(any(word.endswith("appliqu") for phrase in found for word in phrase.split()))


SNEAKER_TITLE = "How to Style New Balance 327 Women's Outfit: Trendy Ideas"
SNEAKER_KEYWORD = "style new balance 327 womens outfit"
SNEAKER_BAD = [
    "actually style",
    "real outfit",
    "casual cool",
    "pretty silhouette",
    "hard way",
    "final words",
    "casual chic",
    "minimalist neutral",
    "perfect for women",
    "outfit ideas womens",
    "closing thoughts",
    "long run",
]
SNEAKER_GOOD = [
    "outfit ideas",
    "street style",
    "wide-leg jeans",
    "summer outfit",
    "neutral outfit",
    "crop top",
    "napkin skirt",
    "office wear",
]


class SneakerFixtureTests(unittest.TestCase):
    def test_filter_rejects_sneaker_garbage_and_keeps_good(self):
        nouns = domain_nouns(SNEAKER_TITLE, SNEAKER_KEYWORD, "Casual Cool: Your Go-to Looks", "Casual Chic")
        for pool in (nouns, set()):
            for phrase in SNEAKER_BAD:
                self.assertFalse(is_search_phrase(phrase, pool), phrase)
            for phrase in SNEAKER_GOOD:
                self.assertTrue(is_search_phrase(phrase, pool), phrase)

    def test_closing_sections_blocked_in_every_path(self):
        for label in ["Final Words", "Final Thoughts", "Wrapping Up", "In Conclusion", "Verdict", "To Sum Up"]:
            self.assertTrue(is_closing_section(label), label)
            self.assertFalse(validate_keyword(label.lower(), SNEAKER_KEYWORD, source="heading", page_relevance=0.5)["accepted"], label)
        self.assertFalse(is_closing_section("Summary Outfit Ideas With New Balance 327"))
        self.assertFalse(is_closing_section("Street Style"))

    def test_heading_derived_garbage_stays_out_of_table(self):
        page = {
            "title": SNEAKER_TITLE,
            "h1": SNEAKER_TITLE,
            "h2_headings": ["Casual Chic: Everyday Street Style", "Minimalist Neutral Outfit Ideas"],
            "text": "Wide-leg jeans and a crop top suit the 327. Summer outfit ideas start here.",
            "full_text": "Wide-leg jeans and a crop top suit the 327. Summer outfit ideas start here.",
            "url": "https://example.com/style-new-balance-327-womens-outfit",
        }
        competitor = {
            "title": "How to Style New Balance 327 Women",
            "url": "https://shoes.example/how-to-style-new-balance-327-women",
            "domain": "shoes.example",
            "h2_headings": [
                "The 327: More Than Just a Pretty Silhouette",
                "Casual Cool: Your Go-to Looks",
                "Things I've Learned the Hard Way",
                "Final Words",
            ],
            "text": "Here is how to actually style them. A real outfit needs balance. Street style works.",
            "full_text": "Here is how to actually style them. A real outfit needs balance. Street style works.",
        }
        report = compare_keywords(SNEAKER_KEYWORD, page, [competitor])
        found = {row["keyword"] for row in report["table"]}
        for phrase in SNEAKER_BAD:
            self.assertNotIn(phrase, found)


_FAKE_POS = {
    "a": "DET", "the": "DET", "it": "PRON", "is": "AUX", "gives": "VERB",
    "casual": "ADJ", "cool": "ADJ", "simple": "ADJ", "clean": "ADJ",
    "look": "NOUN", "purpose": "NOUN", "placemats": "NOUN", "leather": "NOUN",
    "heat": "NOUN", "of": "ADP", "wipe": "VERB", "resist": "VERB",
    "absorb": "VERB", "cork": "VERB", "wide-leg": "ADJ", "jeans": "NOUN",
}


class _FakeToken:
    def __init__(self, text: str):
        self.text = text
        self.text_with_ws = f"{text} "
        self.pos_ = _FAKE_POS.get(text.lower(), "VERB")


class _FakeSpan:
    def __init__(self, doc, start: int, end: int):
        self.doc, self.start, self.end = doc, start, end

    def __iter__(self):
        return iter(self.doc.tokens[self.start:self.end])


class _FakeDoc:
    def __init__(self, text: str):
        self.tokens = [_FakeToken(word) for word in re.findall(r"[\w'-]+", text)]

    def __len__(self):
        return len(self.tokens)

    def __getitem__(self, index):
        return self.tokens[index]

    @property
    def noun_chunks(self):
        spans, start = [], None
        for index, token in enumerate(self.tokens + [None]):
            if token is not None and token.pos_ in {"DET", "ADJ", "NOUN", "PROPN"}:
                start = index if start is None else start
                continue
            if start is not None:
                end = index
                while end > start and self.tokens[end - 1].pos_ not in {"NOUN", "PROPN"}:
                    end -= 1
                if end > start:
                    spans.append(_FakeSpan(self, start, end))
            start = None
        return spans


class _FakeNLP:
    def pipe(self, texts, batch_size=64):
        return (_FakeDoc(text) for text in texts)


class SpacyGateTests(unittest.TestCase):
    def test_chunks_end_on_nouns_and_join_of_phrases(self):
        with patch("acl_agent.keywords._spacy_nlp", return_value=_FakeNLP()):
            allowed = noun_chunk_phrases(
                "It gives a casual cool look. The purpose of placemats is simple. Wide-leg jeans."
            )
        self.assertIn("casual cool look", allowed)
        self.assertIn("purpose of placemats", allowed)
        self.assertIn("wide-leg jeans", allowed)
        self.assertNotIn("casual cool", allowed)

    def test_gate_filters_extract_terms_when_spacy_loads(self):
        text = "Leather placemats resist heat. Cork placemats absorb heat. " * 2
        with patch("acl_agent.keywords._spacy_nlp", return_value=_FakeNLP()):
            gated = {t["keyword"] for t in extract_terms(text, [], PLACEMAT_KEYWORD, page_title=PLACEMAT_TITLE, page_relevance=0.5)}
        with patch("acl_agent.keywords._spacy_nlp", return_value=None):
            fallback = {t["keyword"] for t in extract_terms(text, [], PLACEMAT_KEYWORD, page_title=PLACEMAT_TITLE, page_relevance=0.5)}
        self.assertIn("leather placemats", gated)
        self.assertNotIn("cork placemats", gated)
        self.assertIn("cork placemats", fallback)

    def test_missing_spacy_returns_none(self):
        with patch("acl_agent.keywords._spacy_nlp", return_value=None):
            self.assertIsNone(noun_chunk_phrases("Leather placemats resist heat."))


def _row(keyword, status, comp_count=0, freq=3, rel=0.6, type_="secondary", placement="body"):
    return {
        "keyword": keyword,
        "type": type_,
        "my_blog_status": status,
        "found_in_my_blog": status != "missing",
        "found_in_competitor": comp_count > 0,
        "competitor_count": comp_count,
        "frequency": freq,
        "relevance_score": rel,
        "prominence": "high" if placement in {"heading", "target"} else "medium",
        "placement": placement,
    }


FOCUS_TABLE = [
    _row("leather placemats", "exact", comp_count=3, freq=6, type_="primary", placement="target"),
    _row("placemat sizes", "exact", comp_count=1, freq=5, placement="heading"),
    _row("washable placemats", "exact", freq=4),
    _row("vinyl placemats", "exact", freq=2),
    _row("table runner pairing", "missing", comp_count=3, freq=4),
    _row("placemat materials", "missing", comp_count=2, freq=3),
    _row("round placemats", "missing", comp_count=1, freq=2),
    _row("seasonal decor", "missing", comp_count=1, freq=2, rel=0.2),
    _row("cork placemats", "close_variant", comp_count=2, freq=3),
]


class GapStrictnessTests(unittest.TestCase):
    KEYWORD = "guide to reusable produce bags"

    def test_vague_heads_are_rejected(self):
        self.assertEqual(search_phrase_check("initial things"), "vague_head")
        self.assertEqual(search_phrase_check("kitchen stuff"), "vague_head")

    YOURS = {
        "title": "Guide to Reusable Produce Bags",
        "h2_headings": ["Why switch"],
        "full_text": "Reusable produce bags cut plastic waste. " * 20,
    }
    ODD_COMP = {
        "title": "Produce bag tips",
        "domain": "a.example",
        "h2_headings": ["Veg aisles at the market", "Cotton mesh versus polyester netting"],
        "full_text": ("Veg aisles are busy. Clear bags help cashiers. " * 10)
        + "Wash mesh produce bags in cold water. " * 5,
    }
    PLAIN_COMP = {
        "title": "Mesh produce bags guide",
        "domain": "b.example",
        "h2_headings": ["Cotton mesh versus polyester netting"],
        "full_text": "Wash mesh produce bags in cold water. " * 10,
    }

    def test_one_off_low_relevance_phrase_is_not_high_priority(self):
        report = compare_keywords(self.KEYWORD, self.YOURS, [self.ODD_COMP, self.PLAIN_COMP])
        high = {g["keyword"] for g in report["gaps"]["high-priority"]}
        self.assertNotIn("veg aisles", high)
        self.assertNotIn("clear bags", high)
        plan = action_plan(self.YOURS, {}, report, {"table": []}, {"score": 80})
        self.assertFalse(any("veg aisles" in p["issue"] or "clear bags" in p["issue"] for p in plan))

    def test_one_off_off_topic_heading_is_not_a_content_gap(self):
        topics = {
            row["missing_topic"]
            for row in content_gaps(self.YOURS, [self.ODD_COMP, self.PLAIN_COMP], self.KEYWORD)["table"]
        }
        self.assertNotIn("Veg aisles at the market", topics)
        self.assertIn("Cotton mesh versus polyester netting", topics)


class KeywordFocusTests(unittest.TestCase):
    def test_each_group_is_capped_and_unique(self):
        focus = keyword_focus("leather placemats", FOCUS_TABLE, None, competitor_total=3)
        groups = [focus["our_blog"], focus["competitors"], focus["opportunities"]]
        self.assertTrue(all(len(group) <= 3 for group in groups))
        keys = [item["keyword"] for group in groups for item in group]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(focus["our_blog_basis"], "on_page")
        self.assertEqual(focus["our_blog"][0]["keyword"], "leather placemats")

    def test_competitor_group_ranks_by_competitor_use_and_skips_target(self):
        focus = keyword_focus("leather placemats", FOCUS_TABLE, None, competitor_total=3)
        names = [item["keyword"] for item in focus["competitors"]]
        self.assertEqual(names[0], "table runner pairing")
        self.assertNotIn("leather placemats", names)
        self.assertIn("Used by 3 of 3 competitors", focus["competitors"][0]["evidence"])

    def test_opportunities_are_relevant_gaps_and_volume_is_never_invented(self):
        focus = keyword_focus("leather placemats", FOCUS_TABLE, None, competitor_total=3)
        names = [item["keyword"] for item in focus["opportunities"]]
        self.assertNotIn("seasonal decor", names)
        self.assertTrue(all(item["search_volume"] == "Data unavailable" for item in focus["opportunities"]))
        self.assertIn("Data unavailable", focus["note"])

    def test_search_console_drives_blog_and_opportunities(self):
        gsc = {
            "status": "ok",
            "queries": [
                {"query": "leather placemats", "clicks": 40, "impressions": 900, "position": 4.2},
                {"query": "best placemats for dining table", "clicks": 2, "impressions": 1500, "position": 14.0},
                {"query": "brand store", "clicks": 90, "impressions": 100, "position": 1.0, "branded": True},
            ],
        }
        focus = keyword_focus("leather placemats", FOCUS_TABLE, gsc, competitor_total=3)
        self.assertEqual(focus["our_blog_basis"], "search_console")
        self.assertEqual(focus["our_blog"][0]["keyword"], "leather placemats")
        self.assertIn("40 clicks", focus["our_blog"][0]["evidence"])
        self.assertNotIn("brand store", [item["keyword"] for item in focus["our_blog"]])
        self.assertEqual(focus["opportunities"][0]["source"], "search_console")

    def test_real_volume_from_provider_ranks_opportunities(self):
        class Provider:
            def keyword_volume(self, phrase, country):
                return {"round placemats": 5400}.get(phrase)

        focus = keyword_focus("leather placemats", FOCUS_TABLE, None, competitor_total=3, metrics=Provider())
        self.assertEqual(focus["opportunities"][0]["keyword"], "round placemats")
        self.assertEqual(focus["opportunities"][0]["search_volume"], 5400)
        self.assertEqual(focus["opportunities_basis"], "volume")


if __name__ == "__main__":
    unittest.main()
