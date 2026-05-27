"""Live-work gate + allocation firewall.

The allocation firewall is the structurally critical guarantee — the
EarningInputs dataclass must NOT accept clout-XP, ever.
"""
import dataclasses

import pytest


def test_earning_inputs_has_no_clout_xp_field():
    """KOSCOT LEAK CHECK — clout_xp must not appear in the allocation function's input contract."""
    import gates
    fields = [f.name for f in dataclasses.fields(gates.EarningInputs)]
    assert "clout_xp" not in fields, (
        "FIREWALL REGRESSION: gates.EarningInputs has clout_xp field. "
        "Clout-XP must never influence prospect allocation."
    )
    assert "invite_count" not in fields
    assert "post_count" not in fields
    assert "rank" not in fields
    assert "social_score" not in fields


def test_earning_inputs_allows_only_money_inputs():
    """Whitelist what IS allowed."""
    import gates
    fields = set(f.name for f in dataclasses.fields(gates.EarningInputs))
    allowed = {"money_xp", "drill_cert_score", "close_rate", "tenure_days"}
    assert fields == allowed, f"EarningInputs has unexpected fields: {fields - allowed}"


def test_priority_function_does_not_accept_clout_kwarg():
    """Smoke test — even passing clout_xp as a kwarg fails because EarningInputs has no slot."""
    import gates
    with pytest.raises(TypeError):
        gates.EarningInputs(money_xp=100, drill_cert_score=0.5, close_rate=0.5, tenure_days=10, clout_xp=999)


def test_gate_refuses_with_no_entity_setup(patched_repo):
    """A bare bullpen with no entity setup refuses live work."""
    import gates
    g = gates.can_claim_live_prospect("bp-test", "alice")
    assert not g.ok
    assert "operator_entity_not_set_up" in g.missing


def test_gate_refuses_unsigned_closer(patched_repo, good_operator_entity, contractor_classification):
    """Entity + classification set up — but closer has no agreement signed."""
    import gates
    g = gates.can_claim_live_prospect("bp-test", "alice")
    assert not g.ok
    assert "closer_agreement_not_signed" in g.missing
    assert "w9_not_on_file" in g.missing
    assert "closer_disclosure_not_accepted" in g.missing


def test_gate_lists_all_missing_items(patched_repo, good_operator_entity, contractor_classification):
    """The gate must enumerate every missing item, not bail on the first."""
    import gates
    g = gates.can_claim_live_prospect("bp-test", "alice")
    # Expect at least: closer agreement, w9, disclosure, drill cert
    expected = {"closer_agreement_not_signed", "w9_not_on_file",
                "closer_disclosure_not_accepted", "drill_certification_not_cleared"}
    assert expected.issubset(set(g.missing)), f"Missing items expected: {expected - set(g.missing)}"


def test_gate_passes_when_everything_is_in_place(patched_repo, good_operator_entity, contractor_classification):
    """Full happy path — disclosure accepted, agreement signed, W-9 on file, drill cert cleared."""
    import audit, gates, legal, disclosures, xp

    # 1. Render + sign closer-disclosure
    legal.render_from_template("bp-test", template="closer-disclosure")
    disclosures.accept_closer_disclosure(
        "bp-test", "alice",
        closer_legal_name="Alice Closer",
        typed_signature="Alice Closer",
    )

    # 2. Render closer-agreement w/ closer vars then dual-sign
    legal.render_from_template("bp-test", template="closer-agreement",
        extra_vars={
            "closer_legal_name": "Alice Closer",
            "closer_address": "1 Closer Ln, Eugene OR 97401",
            "signed_date": "2026-05-26",
            "commission_pct": "40",
            "payment_days": "7",
            "payment_rail": "Stripe",
            "notice_days": "14",
            "posttermination_window": "30",
            "chargeback_window": "60",
            "nonsolicit_months": "6",
            "services_scope": "outbound sales",
            "operator_signer_name": "Test Operator",
            "operator_signer_title": "Founder",
        })
    legal.dual_sign("bp-test", doc="closer-agreement",
        operator_signer="operator", operator_typed_name="Test Industries LLC",
        closer_rep="alice", closer_typed_name="Alice Closer",
        closer_legal_name="Alice Closer")

    # 3. Submit W-9
    disclosures.submit_w9("bp-test", "alice",
        legal_name="Alice Closer",
        business_name=None,
        federal_tax_classification="individual",
        address={"street": "1 Closer Ln", "city": "Eugene", "state": "OR",
                 "postal_code": "97401", "country": "US"},
        raw_tin="123-45-6789")

    # 4. Drill certification cleared — emit a cert-tier drill_passed
    audit.append("bp-test", "alice", "drill_passed", payload={"phase_tier": 3})
    xp.invalidate("bp-test")

    g = gates.can_claim_live_prospect("bp-test", "alice")
    assert g.ok, f"Gate should pass but missing: {g.missing}"


def test_priority_scales_with_money_xp_only(patched_repo):
    """priority must be monotone in money_xp + cert_score + close_rate — nothing else."""
    import gates
    low = gates.EarningInputs(money_xp=100, drill_cert_score=0.5, close_rate=0.3, tenure_days=10)
    high = gates.EarningInputs(money_xp=100000, drill_cert_score=0.5, close_rate=0.3, tenure_days=10)
    assert gates.prospect_claim_priority(high) > gates.prospect_claim_priority(low)


def test_team_claim_with_bullpen_arg_fires_gate(patched_repo):
    """team.claim() with bullpen= should invoke the gate. With no setup, should refuse."""
    import team
    r = team.claim("test-prospect", "alice", bullpen="bp-test")
    assert not r.get("ok"), "claim with no setup should fail gate"
    assert r.get("error") == "live_work_gate_refused"
