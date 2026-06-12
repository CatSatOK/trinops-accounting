"""Anomaly detector tests: arithmetic rules, no API calls."""

from datetime import date, timedelta

from accounting.ap.anomaly_detector import detect_anomalies
from accounting.ap.parser import ParsedInvoice
from accounting.models import InboundInvoice

TODAY = date(2026, 6, 12)


def _parsed(**overrides) -> ParsedInvoice:
    defaults = dict(
        vendor="Supplier X",
        invoice_number="INV-1",
        amount=120.00,
        vat_amount=20.00,
        invoice_date=TODAY - timedelta(days=10),
    )
    defaults.update(overrides)
    return ParsedInvoice(**defaults)


def test_clean_invoice_has_no_flags(session, settings):
    flags = detect_anomalies(_parsed(), session, settings, today=TODAY)
    assert flags == []


def test_missing_vat(session, settings):
    flags = detect_anomalies(_parsed(vat_amount=None), session, settings, today=TODAY)
    assert "missing VAT" in flags


def test_vat_mismatch(session, settings):
    # gross 540, vat 60 → net 480, expected VAT at 20% is 96
    flags = detect_anomalies(
        _parsed(amount=540.00, vat_amount=60.00), session, settings, today=TODAY
    )
    assert any("VAT mismatch" in f for f in flags)


def test_vat_within_tolerance_passes(session, settings):
    # gross 144, vat 24 → net 120, expected 24.00 exactly
    flags = detect_anomalies(
        _parsed(amount=144.00, vat_amount=24.00), session, settings, today=TODAY
    )
    assert flags == []


def test_future_date(session, settings):
    flags = detect_anomalies(
        _parsed(invoice_date=TODAY + timedelta(days=21)), session, settings, today=TODAY
    )
    assert "invoice dated in the future" in flags


def test_date_older_than_a_year(session, settings):
    flags = detect_anomalies(
        _parsed(invoice_date=TODAY - timedelta(days=400)), session, settings, today=TODAY
    )
    assert "invoice older than a year" in flags


def test_duplicate_same_vendor_and_amount(session, settings):
    session.add(
        InboundInvoice(
            vendor="Supplier X",
            amount=120.00,
            invoice_date=TODAY - timedelta(days=5),
            raw_email_id="existing-1",
        )
    )
    session.flush()
    flags = detect_anomalies(_parsed(), session, settings, today=TODAY)
    assert any("duplicate" in f for f in flags)


def test_old_match_is_not_a_duplicate(session, settings):
    session.add(
        InboundInvoice(
            vendor="Supplier X",
            amount=120.00,
            invoice_date=TODAY - timedelta(days=90),
            raw_email_id="existing-2",
        )
    )
    session.flush()
    flags = detect_anomalies(_parsed(), session, settings, today=TODAY)
    assert flags == []


def test_incomplete_extraction_is_flagged(session, settings):
    flags = detect_anomalies(
        ParsedInvoice(method="failed"), session, settings, today=TODAY
    )
    assert "extraction incomplete" in flags
