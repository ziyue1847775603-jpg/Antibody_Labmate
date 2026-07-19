"""Syntactic validation for six explicitly separated IMGT CDR strings."""

import re

from labmate.config import DEFAULT_INPUT_LIMITS
from labmate.errors import InputValidationError

STANDARD_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")


def normalize_cdr_sequence(value: str, *, field_name: str = "CDR") -> str:
    """Remove whitespace/FASTA headers, uppercase, and validate amino-acid syntax.

    This deliberately does not claim that a short sequence is biologically mapped
    to the correct IMGT region. Phase 1 has no locked IgCraft tokenizer, so the
    length ceiling is only a configurable input-safety bound.
    """

    if not isinstance(value, str):
        raise InputValidationError(f"{field_name} 必须是字符串")

    sequence_lines = [
        line.strip() for line in value.splitlines() if line.strip() and not line.lstrip().startswith(">")
    ]
    sequence = re.sub(r"\s+", "", "".join(sequence_lines)).upper()
    if not sequence:
        raise InputValidationError(f"{field_name} 不能为空")
    if len(sequence) > DEFAULT_INPUT_LIMITS.max_cdr_length:
        raise InputValidationError(
            f"{field_name} 超过 Replay P0 的安全长度上限 {DEFAULT_INPUT_LIMITS.max_cdr_length}"
        )

    illegal = sorted(set(sequence) - STANDARD_AMINO_ACIDS)
    if illegal:
        raise InputValidationError(f"{field_name} 含非法或不明确残基: {', '.join(illegal)}")
    return sequence

