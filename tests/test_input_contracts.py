from labmate.docking.registry import capability_matrix


def test_machine_readable_input_boundary_is_truthful() -> None:
    contracts = capability_matrix()["input_contracts"]
    assert contracts["replay_cdr_demo"] is True
    assert contracts["live_cdr_to_sequence"] is False
    assert contracts["live_complete_vh_vl_input"] is True
    assert contracts["igcraft_audited"] is True
    assert contracts["igcraft_integrated"] is False
    assert contracts["igcraft_block_reason"] == "input_contract_mismatch"


def test_public_input_contract_docs_do_not_claim_cdr_live_generation(project_root) -> None:
    docs = (project_root / "docs" / "input_contracts.md").read_text(encoding="utf-8")
    evaluation = (project_root / "docs" / "igcraft_evaluation.md").read_text(encoding="utf-8")
    assert "not implemented" in docs
    assert "not integrated" in evaluation
    assert "/" + "mnt" + "/d/igcraft" not in evaluation
