"""Classification coach — refuses obvious-employee, fires AB5 (B) veto in CA."""
import pytest


def test_obvious_contractor_passes():
    """Every answer flipped contractor-leaning = verdict contractor."""
    import classification
    answers = {q["id"]: (q["score_yes"] == 1) for q in classification.QUESTIONS}
    result = classification.score(answers, operator_state="OR")
    assert result["verdict"] == "contractor"
    assert result["total_score"] >= 6


def test_obvious_employee_refuses():
    """Every answer flipped employee-leaning = verdict employee, render refused."""
    import classification
    answers = {q["id"]: (q["score_yes"] == -1) for q in classification.QUESTIONS}
    ok, result = classification.can_render_1099(answers, operator_state="OR")
    assert not ok
    assert result["verdict"] == "employee"


def test_ab5_b_veto_fires_in_california():
    """AB5 (B): work must be OUTSIDE operator's usual business. In CA, if core_business_function is False, veto fires."""
    import classification
    answers = {q["id"]: (q["score_yes"] == 1) for q in classification.QUESTIONS}
    answers["core_business_function"] = False
    ok, result = classification.can_render_1099(answers, operator_state="CA")
    assert not ok
    assert "ab5_b_in_california" in result["veto_failures"]


def test_ab5_b_does_not_veto_outside_california():
    """In OR or NY, AB5 (B) veto doesn't fire even with the same answers."""
    import classification
    answers = {q["id"]: (q["score_yes"] == 1) for q in classification.QUESTIONS}
    answers["core_business_function"] = False
    result_or = classification.score(answers, operator_state="OR")
    assert "ab5_b_in_california" not in result_or["veto_failures"]


def test_state_warnings_appear_for_high_risk_states():
    """CA, NJ, NY, IL, LA should each have a state-specific warning surfaced."""
    import classification
    answers = {q["id"]: (q["score_yes"] == 1) for q in classification.QUESTIONS}
    for state in ["CA", "NJ", "NY", "IL", "LA"]:
        result = classification.score(answers, operator_state=state)
        assert len(result["warnings"]) > 0, f"No warnings for {state}"


def test_borderline_does_not_render(patched_repo, good_operator_entity):
    """Borderline verdict refuses 1099 render — gate-side."""
    import classification
    # Pick exactly 3 contractor-leaning answers — sub-6 score, borderline range
    cluster_contractor = [q["id"] for q in classification.QUESTIONS if q["score_yes"] == 1]
    answers = {q["id"]: False for q in classification.QUESTIONS}
    for qid in cluster_contractor[:4]:
        answers[qid] = True

    result = classification.score(answers, operator_state="OR")
    assert result["verdict"] in ("borderline", "employee")
    classification.save_answers("bp-test", answers=answers, operator_state="OR")
    ok, why = classification.jurisdiction_ok_for_closer("bp-test", "alice")
    assert not ok


def test_questionnaire_has_three_clusters():
    """All three IRS clusters represented."""
    import classification
    clusters = {q["cluster"] for q in classification.QUESTIONS}
    assert clusters == {"behavioral", "financial", "relationship"}
