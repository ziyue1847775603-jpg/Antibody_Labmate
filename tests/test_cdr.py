from __future__ import annotations

import pytest
from pydantic import ValidationError

from labmate.errors import InputValidationError
from labmate.models import CDRInput, JobSpec
from labmate.validators.cdr import normalize_cdr_sequence


def test_normalizes_whitespace_case_and_fasta_header() -> None:
    assert normalize_cdr_sequence(">H-CDR1\ngf tf\nssya", field_name="h_cdr1") == "GFTFSSYA"


@pytest.mark.parametrize("value", ["", "\n>header\n", "ABCX", "PEPTIDE*"])
def test_rejects_empty_or_nonstandard_residues(value: str) -> None:
    with pytest.raises(InputValidationError):
        normalize_cdr_sequence(value)


def test_rejects_p0_safety_length_overflow() -> None:
    with pytest.raises(InputValidationError, match="安全长度上限"):
        normalize_cdr_sequence("A" * 81, field_name="h_cdr3")


def test_cdr_model_normalizes_all_six_fields() -> None:
    cdr = CDRInput(
        h_cdr1=" aa ",
        h_cdr2="cc",
        h_cdr3="DD",
        l_cdr1="ee",
        l_cdr2="ff",
        l_cdr3="gg",
    )
    assert cdr.region_map() == {
        "H-cdr1": "AA",
        "H-cdr2": "CC",
        "H-cdr3": "DD",
        "L-cdr1": "EE",
        "L-cdr2": "FF",
        "L-cdr3": "GG",
    }


def test_job_requires_rights_confirmation(demo_job: JobSpec) -> None:
    payload = demo_job.model_dump(mode="json")
    payload["rights_confirmed"] = False
    with pytest.raises(ValidationError, match="确认"):
        JobSpec.model_validate(payload)

