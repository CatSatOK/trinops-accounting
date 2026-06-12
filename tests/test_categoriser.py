"""Categoriser tests: keyword rules, vendor weighting, default."""

from accounting.ap.categoriser import DEFAULT_CATEGORY, categorise


def test_categorises_from_body_keywords(settings):
    assert categorise("fuel charges and hotel for site visit", None, settings) == "Travel"


def test_vendor_name_outweighs_body(settings):
    # vendor keyword scores double, so 'Travel' in the name beats one body hit
    category = categorise("annual licence renewal", "Supplier Y Travel", settings)
    assert category == "Travel"


def test_software_keywords(settings):
    category = categorise(
        "cloud hosting subscription - monthly\nbackup storage licence",
        "Supplier X Cloud Services",
        settings,
    )
    assert category == "Software"


def test_no_match_falls_back_to_default(settings):
    assert categorise("miscellaneous charge", "Supplier Q", settings) == DEFAULT_CATEGORY


def test_case_insensitive(settings):
    assert categorise("ELECTRICITY SUPPLY - WORKSHOP", None, settings) == "Utilities"
