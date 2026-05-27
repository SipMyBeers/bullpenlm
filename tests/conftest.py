"""Shared pytest fixtures for the Phase 0.5 firewall tests.

Each test gets a temporary REPO directory so the modules write to
fixture-local paths instead of the live ~/bullpenlm/bullpens/. Module-
level REPO and BULLPENS_ROOT are monkeypatched per test.
"""
import sys
import tempfile
import shutil
from pathlib import Path

import pytest

# Ensure server/ is importable
SERVER_DIR = Path(__file__).parent.parent / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


@pytest.fixture()
def tmp_repo(tmp_path: Path):
    """A temporary repo dir + bullpens subdir. Returns the path."""
    bullpens = tmp_path / "bullpens"
    bullpens.mkdir()
    return tmp_path


@pytest.fixture()
def patched_repo(tmp_repo, monkeypatch):
    """Monkeypatch every Phase 0.5 module's REPO + BULLPENS_ROOT to point
    at the tmp dir. Also points the legal template directory at the
    real repo so templates can be rendered."""
    import audit, entity, classification, dnc, disclosures, gates, legal, payouts, xp
    real_templates = Path(__file__).parent.parent / "templates" / "legal"

    for mod in (audit, entity, classification, dnc, disclosures, gates, legal, payouts):
        monkeypatch.setattr(mod, "REPO", tmp_repo, raising=False)
        if hasattr(mod, "BULLPENS_ROOT"):
            monkeypatch.setattr(mod, "BULLPENS_ROOT", tmp_repo / "bullpens", raising=False)
    monkeypatch.setattr(legal, "TEMPLATE_DIR", real_templates, raising=False)
    # disclosures._read_template reads from REPO/templates/legal — symlink
    # the real templates under tmp so the lookup works without monkeypatching
    # the function itself.
    tmp_tpl = tmp_repo / "templates" / "legal"
    tmp_tpl.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp_tpl.symlink_to(real_templates, target_is_directory=True)
    except (OSError, FileExistsError):
        shutil.copytree(real_templates, tmp_tpl, dirs_exist_ok=True)
    # XP cache is per-bullpen — reset it.
    xp._xp_cache.clear()
    return tmp_repo


@pytest.fixture()
def good_operator_entity(patched_repo):
    """A bullpen with a fully configured contractor-leaning operator."""
    import entity
    return entity.set_entity(
        "bp-test",
        kind="llc",
        legal_name="Test Industries LLC",
        raw_ein_or_ssn="12-3456789",
        address={
            "street": "1 Test St", "city": "Portland",
            "state": "OR", "postal_code": "97201", "country": "US",
        },
        jurisdiction="US-OR",
        contact_email="ops@test.com",
    )


@pytest.fixture()
def contractor_classification(patched_repo, good_operator_entity):
    """Classification answers that score full-contractor."""
    import classification
    answers = {q["id"]: (q["score_yes"] == 1) for q in classification.QUESTIONS}
    return classification.save_answers("bp-test", answers=answers, operator_state="OR")
