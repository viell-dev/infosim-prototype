from __future__ import annotations

from infosim.actors import Traits
from infosim.personnel import Candidate, pick_replacement


def _candidates() -> list[Candidate]:
    return [
        Candidate(id="loyal_dunce", display_name="L", traits=Traits(
            competence=0.2, honesty=0.5, loyalty=0.99, education=0.3)),
        Candidate(id="genius", display_name="G", traits=Traits(
            competence=0.99, honesty=0.5, loyalty=0.2, education=0.99)),
        Candidate(id="balanced", display_name="B", traits=Traits(
            competence=0.6, honesty=0.6, loyalty=0.6, education=0.6)),
    ]


def test_paranoid_king_prefers_loyalty() -> None:
    paranoid = Traits(competence=0.5, honesty=0.5, fear=1.0, education=0.3)
    pick = pick_replacement(_candidates(), used_ids=set(), king_traits=paranoid)
    assert pick is not None
    assert pick.id == "loyal_dunce"


def test_scholar_king_prefers_competence() -> None:
    scholar = Traits(competence=0.5, honesty=0.5, fear=0.0, education=1.0)
    pick = pick_replacement(_candidates(), used_ids=set(), king_traits=scholar)
    assert pick is not None
    assert pick.id == "genius"


def test_used_candidates_skipped() -> None:
    scholar = Traits(competence=0.5, honesty=0.5, fear=0.0, education=1.0)
    pick = pick_replacement(_candidates(), used_ids={"genius"}, king_traits=scholar)
    assert pick is not None
    assert pick.id != "genius"


def test_empty_pool_returns_none() -> None:
    assert pick_replacement([], used_ids=set(), king_traits=Traits()) is None
