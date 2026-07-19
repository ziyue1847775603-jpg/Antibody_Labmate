"""Small, dependency-free PDB parser for Replay input and interface analysis.

The parser intentionally implements only the fixed-column records needed by the
MVP. It keeps the first MODEL, accepts ATOM records from selected protein chains,
and chooses blank altloc before A. It never downloads structures or repairs
missing regions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

from labmate.config import DEFAULT_INPUT_LIMITS, InputLimits
from labmate.errors import InputValidationError

STANDARD_RESIDUES = frozenset(
    {
        "ALA",
        "ARG",
        "ASN",
        "ASP",
        "CYS",
        "GLN",
        "GLU",
        "GLY",
        "HIS",
        "ILE",
        "LEU",
        "LYS",
        "MET",
        "PHE",
        "PRO",
        "SER",
        "THR",
        "TRP",
        "TYR",
        "VAL",
    }
)

THREE_TO_ONE = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}


@dataclass(frozen=True)
class ResidueKey:
    chain_id: str
    residue_number: int
    insertion_code: str
    residue_name: str

    @property
    def display_number(self) -> str:
        return f"{self.residue_number}{self.insertion_code}" if self.insertion_code else str(self.residue_number)


@dataclass(frozen=True)
class AtomRecord:
    serial: int
    name: str
    altloc: str
    residue: ResidueKey
    x: float
    y: float
    z: float
    occupancy: float | None
    element: str

    @property
    def is_hydrogen(self) -> bool:
        return self.element.upper() == "H" or self.name.strip().upper().startswith("H")


@dataclass
class PDBParseResult:
    atoms: list[AtomRecord]
    chains: list[str]
    residue_count: int
    model_count: int
    selected_model: int
    removed_hetero_atoms: int = 0
    removed_nonstandard_atoms: int = 0
    removed_altloc_atoms: int = 0
    ignored_model_atoms: int = 0
    warnings: list[str] = field(default_factory=list)
    residue_mapping: list[dict[str, str | int]] = field(default_factory=list)
    cleaned_pdb: str = ""


def _parse_int(text: str, label: str, line_number: int) -> int:
    try:
        return int(text.strip())
    except ValueError as exc:
        raise InputValidationError(f"PDB 第 {line_number} 行的 {label} 无效") from exc


def _parse_float(text: str, label: str, line_number: int) -> float:
    try:
        value = float(text.strip())
    except ValueError as exc:
        raise InputValidationError(f"PDB 第 {line_number} 行的 {label} 无效") from exc
    if not isfinite(value):
        raise InputValidationError(f"PDB 第 {line_number} 行的 {label} 不是有限数")
    return value


def _format_atom(atom: AtomRecord, serial: int) -> str:
    atom_name = atom.name[:4]
    element = (atom.element or atom_name.strip()[:1]).upper()[:2]
    occupancy = atom.occupancy if atom.occupancy is not None else 1.0
    return (
        f"ATOM  {serial:5d} {atom_name:>4s} {atom.residue.residue_name:>3s} "
        f"{atom.residue.chain_id:1s}{atom.residue.residue_number:4d}{atom.residue.insertion_code:1s}   "
        f"{atom.x:8.3f}{atom.y:8.3f}{atom.z:8.3f}{occupancy:6.2f}{20.00:6.2f}"
        f"          {element:>2s}  "
    )


def parse_antigen_pdb(
    data: bytes,
    *,
    selected_chains: list[str] | None = None,
    limits: InputLimits = DEFAULT_INPUT_LIMITS,
) -> PDBParseResult:
    """Parse and clean a protein PDB upload under bounded resource limits."""

    if not data:
        raise InputValidationError("抗原 PDB 为空")
    if len(data) > limits.max_pdb_bytes:
        raise InputValidationError(f"抗原 PDB 超过 {limits.max_pdb_bytes} 字节限制")
    if b"\x00" in data:
        raise InputValidationError("抗原 PDB 含 NUL 字节")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputValidationError("抗原 PDB 必须是 UTF-8/ASCII 文本") from exc

    requested = list(dict.fromkeys(selected_chains or []))
    atoms_by_key: dict[tuple[str, int, str, str, str], tuple[int, AtomRecord]] = {}
    observed_chains: list[str] = []
    model_count = 0
    current_model = 1
    first_model = 1
    saw_model_record = False
    in_selected_model = True
    removed_hetero = 0
    removed_nonstandard = 0
    removed_altloc = 0
    ignored_model_atoms = 0

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.ljust(80)
        record = line[0:6].strip().upper()
        if record == "MODEL":
            saw_model_record = True
            model_count += 1
            current_model = _parse_int(line[10:14], "MODEL 编号", line_number)
            if model_count == 1:
                first_model = current_model
            in_selected_model = model_count == 1
            continue
        if record == "ENDMDL":
            in_selected_model = False
            continue
        if record not in {"ATOM", "HETATM"}:
            continue
        if not in_selected_model:
            ignored_model_atoms += 1
            continue
        if record == "HETATM":
            removed_hetero += 1
            continue

        chain_id = line[21].strip() or "_"
        if chain_id not in observed_chains:
            observed_chains.append(chain_id)
            if len(observed_chains) > limits.max_pdb_chains:
                raise InputValidationError(f"PDB 链数超过 {limits.max_pdb_chains}")
        if requested and chain_id not in requested:
            continue

        residue_name = line[17:20].strip().upper()
        if residue_name not in STANDARD_RESIDUES:
            removed_nonstandard += 1
            continue
        altloc = line[16].strip().upper()
        if altloc not in {"", "A"}:
            removed_altloc += 1
            continue
        residue_number = _parse_int(line[22:26], "残基编号", line_number)
        insertion_code = line[26].strip()
        atom_name = line[12:16].strip()
        serial = _parse_int(line[6:11], "原子序号", line_number)
        x = _parse_float(line[30:38], "X 坐标", line_number)
        y = _parse_float(line[38:46], "Y 坐标", line_number)
        z = _parse_float(line[46:54], "Z 坐标", line_number)
        occupancy_text = line[54:60].strip()
        occupancy = _parse_float(occupancy_text, "occupancy", line_number) if occupancy_text else None
        element = line[76:78].strip().upper() or atom_name[:1].upper()
        residue = ResidueKey(chain_id, residue_number, insertion_code, residue_name)
        atom = AtomRecord(serial, atom_name, altloc, residue, x, y, z, occupancy, element)
        key = (chain_id, residue_number, insertion_code, residue_name, atom_name)
        priority = 2 if altloc == "" else 1
        previous = atoms_by_key.get(key)
        if previous is None or priority > previous[0]:
            if previous is not None:
                removed_altloc += 1
            atoms_by_key[key] = (priority, atom)
        else:
            removed_altloc += 1
        if len(atoms_by_key) > limits.max_pdb_atoms:
            raise InputValidationError(f"PDB 原子数超过 {limits.max_pdb_atoms}")

    if not saw_model_record:
        model_count = 1
        first_model = 1

    atoms = [item[1] for item in atoms_by_key.values()]
    atoms.sort(
        key=lambda atom: (
            atom.residue.chain_id,
            atom.residue.residue_number,
            atom.residue.insertion_code,
            atom.serial,
        )
    )
    if not atoms:
        raise InputValidationError("所选链没有可用的标准蛋白 ATOM 坐标")

    selected = list(dict.fromkeys(atom.residue.chain_id for atom in atoms))
    if requested:
        missing = [chain for chain in requested if chain not in selected]
        if missing:
            raise InputValidationError(f"PDB 缺少所选链: {', '.join(missing)}")
    residues = list(dict.fromkeys(atom.residue for atom in atoms))
    mapping = [
        {
            "original_chain": residue.chain_id,
            "original_residue_number": residue.residue_number,
            "original_insertion_code": residue.insertion_code,
            "cleaned_chain": residue.chain_id,
            "cleaned_residue_number": residue.residue_number,
            "cleaned_insertion_code": residue.insertion_code,
        }
        for residue in residues
    ]
    warnings: list[str] = []
    if model_count > 1:
        warnings.append(f"检测到 {model_count} 个 MODEL；仅保留第一个模型 {first_model}")
    if removed_hetero:
        warnings.append(f"删除 {removed_hetero} 个 HETATM 原子")
    if removed_nonstandard:
        warnings.append(f"删除 {removed_nonstandard} 个非标准 ATOM 原子")
    if removed_altloc:
        warnings.append(f"按 blank>A 规则移除 {removed_altloc} 个 altloc 原子")

    cleaned_lines = [_format_atom(atom, serial) for serial, atom in enumerate(atoms, start=1)]
    cleaned_lines.extend(["TER", "END", ""])
    return PDBParseResult(
        atoms=atoms,
        chains=selected,
        residue_count=len(residues),
        model_count=model_count,
        selected_model=first_model,
        removed_hetero_atoms=removed_hetero,
        removed_nonstandard_atoms=removed_nonstandard,
        removed_altloc_atoms=removed_altloc,
        ignored_model_atoms=ignored_model_atoms,
        warnings=warnings,
        residue_mapping=mapping,
        cleaned_pdb="\n".join(cleaned_lines),
    )


def parse_complex_pdb(data: bytes) -> PDBParseResult:
    """Parse a fixed pose while preserving all standard protein chains."""

    return parse_antigen_pdb(data, selected_chains=None)
