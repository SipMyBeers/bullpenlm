"""Closer disclosure + Operator TOS + W-9 acceptance hash-chain into audit."""
import pytest


def test_disclosure_acceptance_requires_legal_name_match(patched_repo, good_operator_entity):
    """Typed signature must match the closer's legal name exactly."""
    import disclosures, legal
    legal.render_from_template("bp-test", template="closer-disclosure")
    with pytest.raises(ValueError):
        disclosures.accept_closer_disclosure(
            "bp-test", "alice",
            closer_legal_name="Alice Closer",
            typed_signature="A. Closer",   # mismatch
        )


def test_disclosure_acceptance_records_sha(patched_repo, good_operator_entity):
    """Accepted disclosure binds to the SHA of the disclosure text."""
    import disclosures, legal
    legal.render_from_template("bp-test", template="closer-disclosure")
    record = disclosures.accept_closer_disclosure(
        "bp-test", "alice",
        closer_legal_name="Alice Closer",
        typed_signature="Alice Closer",
    )
    assert record["disclosure_sha256"]
    assert disclosures.has_accepted_closer_disclosure("bp-test", "alice")


def test_operator_tos_accept(patched_repo, good_operator_entity):
    """Operator TOS acceptance flow works + audit-logs."""
    import disclosures, legal
    legal.render_from_template("bp-test", template="operator-tos")
    record = disclosures.accept_operator_tos(
        "bp-test",
        "operator",
        operator_legal_name="Test Industries LLC",
        typed_signature="Test Industries LLC",
        counsel_consulted=False,
    )
    assert record["counsel_consulted"] is False
    assert disclosures.has_accepted_operator_tos("bp-test")


def test_w9_hashes_tin_only(patched_repo, good_operator_entity):
    """submit_w9 stores tin_sha256 but never the raw TIN."""
    import disclosures
    rec = disclosures.submit_w9(
        "bp-test", "alice",
        legal_name="Alice Closer",
        business_name=None,
        federal_tax_classification="individual",
        address={"street": "1 St", "city": "X", "state": "OR", "postal_code": "97201", "country": "US"},
        raw_tin="123-45-6789",
    )
    assert "tin_sha256" in rec
    assert "raw_tin" not in rec
    assert len(rec["tin_sha256"]) == 64
    # Read it back from disk — must not contain the raw value
    stored = disclosures.get_w9("bp-test", "alice")
    assert "123-45-6789" not in str(stored)


def test_w9_rejects_short_tin(patched_repo, good_operator_entity):
    """Short TIN is rejected."""
    import disclosures
    with pytest.raises(ValueError):
        disclosures.submit_w9(
            "bp-test", "alice",
            legal_name="Alice", business_name=None,
            federal_tax_classification="individual",
            address={"street": "1", "city": "X", "state": "OR", "postal_code": "97201", "country": "US"},
            raw_tin="12345",
        )
