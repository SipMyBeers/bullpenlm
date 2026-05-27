"""Two-ledger XP firewall — the FTC Koscot pyramid leak path must stay closed."""
import pytest


def test_every_rule_has_a_valid_bucket():
    """Module-load validator must catch invalid buckets — re-asserted here
    so test runner sees it explicitly."""
    import xp
    valid = ("money", "clout", "none")
    for r in xp.RULES:
        assert r["bucket"] in valid, f"Rule {r['kind']!r} has invalid bucket {r['bucket']!r}"


def test_recruitment_kinds_award_zero_xp():
    """Inviting another closer/operator must award no money-XP and no clout-XP."""
    import xp
    forbidden_kinds = {"invite_closer", "invite_operator", "closer_joined", "operator_joined"}
    for r in xp.RULES:
        if r["kind"] in forbidden_kinds:
            assert r["bucket"] == "none", (
                f"FIREWALL REGRESSION: rule {r['kind']!r} has bucket {r['bucket']!r}. "
                f"Recruitment events must always be bucket='none'."
            )


def test_invite_event_credits_no_xp_to_inviter(patched_repo):
    """Even if a recruitment event hits the rules table, it credits 0 XP."""
    import audit, xp
    audit.append("bp", "alice", "invite_closer", payload={"invitee": "bob"})
    audit.append("bp", "alice", "closer_joined", payload={"new_closer": "bob"})
    xp.invalidate("bp")
    money = xp.get_money_xp("bp", "alice")
    clout = xp.get_clout_xp("bp", "alice")
    assert money == 0, f"Inviter earned {money} money-XP from recruitment (firewall leak)"
    assert clout == 0, f"Inviter earned {clout} clout-XP from recruitment (firewall leak)"


def test_closed_deal_credits_money_xp_only(patched_repo):
    """deal_closed_won must land in money-XP only, never clout-XP."""
    import audit, xp
    audit.append("bp", "alice", "deal_closed_won", payload={"amount": 15000})
    xp.invalidate("bp")
    assert xp.get_money_xp("bp", "alice") > 0
    assert xp.get_clout_xp("bp", "alice") == 0


def test_drill_attempt_is_clout(patched_repo):
    """drill_attempt is volume = clout, not money."""
    import audit, xp
    audit.append("bp", "alice", "drill_attempt", payload={})
    xp.invalidate("bp")
    assert xp.get_money_xp("bp", "alice") == 0
    assert xp.get_clout_xp("bp", "alice") > 0


def test_cert_tier_drill_pass_is_money(patched_repo):
    """drill_passed at phase_tier >= 3 (cert tier) is money-XP."""
    import audit, xp
    audit.append("bp", "alice", "drill_passed", payload={"phase_tier": 3})
    xp.invalidate("bp")
    assert xp.get_money_xp("bp", "alice") >= 100, "cert-tier drill pass should award >= 100 money-XP"


def test_below_cert_drill_pass_is_clout(patched_repo):
    """drill_passed below phase_tier 3 is clout, not money."""
    import audit, xp
    audit.append("bp", "alice", "drill_passed", payload={"phase_tier": 2})
    xp.invalidate("bp")
    assert xp.get_money_xp("bp", "alice") == 0
    assert xp.get_clout_xp("bp", "alice") > 0


def test_call_uploaded_is_clout(patched_repo):
    """Real calls credit clout (activity); only closing credits money."""
    import audit, xp
    audit.append("bp", "alice", "call", payload={"call_kind": "real"})
    xp.invalidate("bp")
    assert xp.get_money_xp("bp", "alice") == 0
    assert xp.get_clout_xp("bp", "alice") > 0
