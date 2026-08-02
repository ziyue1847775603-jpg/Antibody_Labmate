"""Versioned CAPRI geometry metrics, isolated from legacy benchmark-local code.

The implementation follows the definitions described in the original CAPRI
assessment and DockQ paper.  It intentionally does not compute the continuous
DockQ score and never combines reference geometry with a docking-native score.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from labmate.validators.antigen import STANDARD_RESIDUES, THREE_TO_ONE

METRIC_DEFINITION_ID = "capri_dockq_2016_v1"
CATEGORY_DEFINITION_ID = "capri_quality_dockq_paper_2016_v1"
BACKBONE_ATOMS = ("N", "CA", "C", "O")


@dataclass(frozen=True)
class MetricDefinition:
    schema_version: int = 1
    definition_id: str = METRIC_DEFINITION_ID
    source_name: str = "CAPRI assessment and DockQ original paper"
    source_version: str = "protein-protein 2016"
    source_reference: tuple[str, ...] = (
        "https://doi.org/10.1002/prot.10393",
        "https://doi.org/10.1371/journal.pone.0161879",
        "https://github.com/wallnerlab/DockQ",
    )
    contact_cutoff_angstrom: float = 5.0
    contact_atom_selection: str = "non-hydrogen atoms; residue contact at distance <= 5 A"
    interface_residue_definition: str = (
        "native receptor/ligand residue pair with any non-hydrogen atom distance <= 10 A"
    )
    interface_atom_selection: str = "corresponding N, CA, C, O atoms"
    receptor_alignment_atom_selection: str = "corresponding receptor N, CA, C, O atoms"
    ligand_rmsd_atom_selection: str = "corresponding ligand N, CA, C, O atoms"
    altloc_policy: str = "blank preferred over A; other alternate locations ignored"
    insertion_code_policy: str = "retained in residue identity before sequence correspondence"
    missing_residue_policy: str = (
        "sequence-align exact identities; missing native interface residues fail closed"
    )
    nonstandard_residue_policy: str = (
        "standard amino acids in ATOM/HETATM accepted; other polymer residues unsupported"
    )
    symmetry_policy: str = "no implicit symmetry optimization; explicit semantic chain mapping required"
    capri_thresholds: dict[str, object] = field(
        default_factory=lambda: {
            "high": {"fnat_min": 0.5, "l_rmsd_max_or_i_rmsd_max": [1.0, 1.0]},
            "medium": {
                "branch_1": {
                    "fnat_min": 0.3,
                    "fnat_max_exclusive": 0.5,
                    "l_rmsd_max_or_i_rmsd_max": [5.0, 2.0],
                },
                "branch_2": {
                    "fnat_min": 0.5,
                    "l_rmsd_min_exclusive_and_i_rmsd_min_exclusive": [1.0, 1.0],
                },
            },
            "acceptable": {
                "branch_1": {
                    "fnat_min": 0.1,
                    "fnat_max_exclusive": 0.3,
                    "l_rmsd_max_or_i_rmsd_max": [10.0, 4.0],
                },
                "branch_2": {
                    "fnat_min": 0.3,
                    "l_rmsd_min_exclusive_and_i_rmsd_min_exclusive": [5.0, 2.0],
                },
            },
        }
    )
    notes: str = (
        "Antigen/receptor and antibody/ligand roles come from the benchmark manifest, "
        "not chain length. DockQ continuous thresholds are not used as CAPRI categories."
    )


CAPRI_DOCKQ_2016 = MetricDefinition()


@dataclass(frozen=True)
class CapriCategoryResult:
    category: str
    category_definition_id: str
    matched_rule: str
    fnat: float
    i_rmsd: float
    l_rmsd: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CapriMetrics:
    fnat: float
    i_rmsd: float
    l_rmsd: float
    native_contact_count: int
    recovered_native_contact_count: int
    native_interface_residue_count: int
    interface_atom_count: int
    receptor_alignment_atom_count: int
    ligand_rmsd_atom_count: int
    unmapped_residues: list[str]
    warnings: list[str]
    metric_definition_id: str = METRIC_DEFINITION_ID

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _Atom:
    name: str
    element: str
    coord: tuple[float, float, float]

    @property
    def is_hydrogen(self) -> bool:
        return self.element.upper() == "H" or self.name.upper().startswith("H")


@dataclass
class _Residue:
    chain: str
    number: int
    insertion: str
    name: str
    atoms: dict[str, _Atom]

    @property
    def key(self) -> tuple[str, int, str, str]:
        return self.chain, self.number, self.insertion, self.name

    @property
    def amino_acid(self) -> str:
        return THREE_TO_ONE[self.name]


@dataclass(frozen=True)
class _Structure:
    chains: dict[str, list[_Residue]]
    warnings: list[str]


def _safe_pdb(path: Path, allowed_root: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError("CAPRI metric input must be a regular non-symlink file")
    resolved = path.resolve()
    try:
        resolved.relative_to(allowed_root.resolve())
    except ValueError as exc:
        raise ValueError("CAPRI metric input escaped the allowed root") from exc
    return resolved


def _parse_pdb(path: Path, allowed_root: Path) -> _Structure:
    resolved = _safe_pdb(path, allowed_root)
    text = resolved.read_text(encoding="utf-8", errors="strict")
    residues: dict[tuple[str, int, str, str], _Residue] = {}
    atoms: dict[tuple[str, int, str, str, str], tuple[int, _Atom]] = {}
    warnings: list[str] = []
    model_count = 0
    active_model = True
    saw_model = False
    ignored_altloc = 0
    ignored_nonprotein = 0
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.ljust(80)
        record = line[0:6].strip().upper()
        if record == "MODEL":
            saw_model = True
            model_count += 1
            active_model = model_count == 1
            continue
        if record == "ENDMDL":
            active_model = False
            continue
        if record not in {"ATOM", "HETATM"} or not active_model:
            continue
        residue_name = line[17:20].strip().upper()
        if residue_name not in STANDARD_RESIDUES:
            if record == "ATOM":
                raise ValueError(
                    f"unsupported nonstandard polymer residue at PDB line {line_number}"
                )
            ignored_nonprotein += 1
            continue
        altloc = line[16].strip().upper()
        if altloc not in {"", "A"}:
            ignored_altloc += 1
            continue
        try:
            number = int(line[22:26].strip())
            x = float(line[30:38].strip())
            y = float(line[38:46].strip())
            z = float(line[46:54].strip())
        except ValueError as exc:
            raise ValueError(f"invalid CAPRI PDB coordinates at line {line_number}") from exc
        if not all(math.isfinite(value) for value in (x, y, z)):
            raise ValueError(f"non-finite CAPRI PDB coordinate at line {line_number}")
        chain = line[21].strip() or "_"
        insertion = line[26].strip()
        atom_name = line[12:16].strip().upper()
        element = line[76:78].strip().upper() or atom_name[:1]
        residue_key = (chain, number, insertion, residue_name)
        atom_key = (*residue_key, atom_name)
        priority = 2 if altloc == "" else 1
        previous = atoms.get(atom_key)
        if previous is None or priority > previous[0]:
            if previous is not None:
                ignored_altloc += 1
            atoms[atom_key] = (priority, _Atom(atom_name, element, (x, y, z)))
        else:
            ignored_altloc += 1
        residues.setdefault(
            residue_key,
            _Residue(chain, number, insertion, residue_name, {}),
        )
    if saw_model and model_count != 1:
        raise ValueError("CAPRI metric inputs must contain exactly one MODEL")
    if not atoms:
        raise ValueError("CAPRI metric input contains no supported protein atoms")
    for atom_key, (_, atom) in atoms.items():
        residues[atom_key[:4]].atoms[atom.name] = atom
    chains: dict[str, list[_Residue]] = {}
    for residue in residues.values():
        if residue.atoms:
            chains.setdefault(residue.chain, []).append(residue)
    for chain_residues in chains.values():
        chain_residues.sort(key=lambda residue: (residue.number, residue.insertion))
    if ignored_altloc:
        warnings.append(
            f"ignored {ignored_altloc} alternate-location atom record(s) under blank_then_A policy"
        )
    if ignored_nonprotein:
        warnings.append(
            f"ignored {ignored_nonprotein} non-protein HETATM record(s)"
        )
    return _Structure(chains=chains, warnings=warnings)


def _align_residues(
    model: list[_Residue], native: list[_Residue]
) -> tuple[list[tuple[_Residue, _Residue]], list[str]]:
    """Unique global alignment; only identical residue identities are mapped."""
    left = "".join(residue.amino_acid for residue in model)
    right = "".join(residue.amino_acid for residue in native)
    rows, columns = len(left), len(right)
    score = [[0.0] * (columns + 1) for _ in range(rows + 1)]
    ways = [[1] * (columns + 1) for _ in range(rows + 1)]
    trace = [[""] * (columns + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        score[i][0] = -4.0 * i
        trace[i][0] = "U"
    for j in range(1, columns + 1):
        score[0][j] = -4.0 * j
        trace[0][j] = "L"
    for i in range(1, rows + 1):
        for j in range(1, columns + 1):
            candidates = {
                "D": score[i - 1][j - 1] + (5.0 if left[i - 1] == right[j - 1] else 0.0),
                "U": score[i - 1][j] - 4.0,
                "L": score[i][j - 1] - 4.0,
            }
            best = max(candidates.values())
            directions = [direction for direction, value in candidates.items() if value == best]
            score[i][j] = best
            ways[i][j] = min(
                2,
                sum(
                    ways[i - 1][j - 1]
                    if direction == "D"
                    else ways[i - 1][j]
                    if direction == "U"
                    else ways[i][j - 1]
                    for direction in directions
                ),
            )
            trace[i][j] = directions[0]
    if ways[rows][columns] != 1:
        raise ValueError("ambiguous residue sequence mapping")
    pairs: list[tuple[_Residue, _Residue]] = []
    unmapped: list[str] = []
    i, j = rows, columns
    while i or j:
        direction = trace[i][j]
        if direction == "D":
            if left[i - 1] == right[j - 1]:
                pairs.append((model[i - 1], native[j - 1]))
            else:
                unmapped.extend(
                    [
                        f"model:{model[i - 1].chain}:{model[i - 1].number}{model[i - 1].insertion}",
                        f"native:{native[j - 1].chain}:{native[j - 1].number}{native[j - 1].insertion}",
                    ]
                )
            i -= 1
            j -= 1
        elif direction == "U":
            unmapped.append(
                f"model:{model[i - 1].chain}:{model[i - 1].number}{model[i - 1].insertion}"
            )
            i -= 1
        elif direction == "L":
            unmapped.append(
                f"native:{native[j - 1].chain}:{native[j - 1].number}{native[j - 1].insertion}"
            )
            j -= 1
        else:
            raise ValueError("residue sequence mapping failed")
    pairs.reverse()
    if not pairs:
        raise ValueError("no identical residues could be mapped")
    return pairs, sorted(unmapped)


def _validate_chain_mapping(
    model: _Structure,
    native: _Structure,
    *,
    model_receptor_chains: tuple[str, ...],
    model_ligand_chains: tuple[str, ...],
    native_receptor_chains: tuple[str, ...],
    native_ligand_chains: tuple[str, ...],
    chain_mapping: dict[str, str],
) -> None:
    model_groups = set(model_receptor_chains) | set(model_ligand_chains)
    native_groups = set(native_receptor_chains) | set(native_ligand_chains)
    if set(model_receptor_chains) & set(model_ligand_chains):
        raise ValueError("model receptor and ligand chain groups overlap")
    if set(native_receptor_chains) & set(native_ligand_chains):
        raise ValueError("native receptor and ligand chain groups overlap")
    if set(chain_mapping) != model_groups or set(chain_mapping.values()) != native_groups:
        raise ValueError("semantic chain mapping must exactly cover receptor and ligand groups")
    if any(chain not in model.chains for chain in model_groups):
        raise ValueError("model is missing a declared semantic chain")
    if any(chain not in native.chains for chain in native_groups):
        raise ValueError("native reference is missing a declared semantic chain")
    if any(chain_mapping[chain] not in native_receptor_chains for chain in model_receptor_chains):
        raise ValueError("receptor chain mapping conflicts with semantic roles")
    if any(chain_mapping[chain] not in native_ligand_chains for chain in model_ligand_chains):
        raise ValueError("ligand chain mapping conflicts with semantic roles")


def _distance(left: _Atom, right: _Atom) -> float:
    return math.dist(left.coord, right.coord)


def _contacts(
    receptor: list[_Residue],
    ligand: list[_Residue],
    *,
    cutoff: float,
) -> set[tuple[tuple[str, int, str, str], tuple[str, int, str, str]]]:
    contacts = set()
    for left in receptor:
        left_atoms = [atom for atom in left.atoms.values() if not atom.is_hydrogen]
        for right in ligand:
            right_atoms = [atom for atom in right.atoms.values() if not atom.is_hydrogen]
            if any(
                _distance(left_atom, right_atom) <= cutoff
                for left_atom in left_atoms
                for right_atom in right_atoms
            ):
                contacts.add((left.key, right.key))
    return contacts


def _kabsch(
    moving: list[tuple[float, float, float]],
    fixed: list[tuple[float, float, float]],
) -> tuple[np.ndarray, np.ndarray, float]:
    if len(moving) != len(fixed) or len(moving) < 3:
        raise ValueError("CAPRI alignment requires at least three corresponding atoms")
    moving_array = np.asarray(moving, dtype=float)
    fixed_array = np.asarray(fixed, dtype=float)
    moving_center = moving_array.mean(axis=0)
    fixed_center = fixed_array.mean(axis=0)
    centered_moving = moving_array - moving_center
    centered_fixed = fixed_array - fixed_center
    if np.linalg.matrix_rank(centered_moving) < 2 or np.linalg.matrix_rank(centered_fixed) < 2:
        raise ValueError("CAPRI alignment atom set is geometrically degenerate")
    covariance = centered_moving.T @ centered_fixed
    left, _, right = np.linalg.svd(covariance)
    rotation = left @ right
    if np.linalg.det(rotation) < 0:
        left[:, -1] *= -1
        rotation = left @ right
    translation = fixed_center - moving_center @ rotation
    transformed = moving_array @ rotation + translation
    rmsd = float(np.sqrt(np.mean(np.sum((transformed - fixed_array) ** 2, axis=1))))
    if not math.isfinite(rmsd):
        raise ValueError("CAPRI alignment produced a non-finite RMSD")
    return rotation, translation, rmsd


def _corresponding_backbone(
    pairs: list[tuple[_Residue, _Residue]],
    *,
    native_subset: set[tuple[str, int, str, str]] | None = None,
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]], int]:
    moving: list[tuple[float, float, float]] = []
    fixed: list[tuple[float, float, float]] = []
    used_residues = 0
    for model_residue, native_residue in pairs:
        if native_subset is not None and native_residue.key not in native_subset:
            continue
        common = [
            atom_name
            for atom_name in BACKBONE_ATOMS
            if atom_name in model_residue.atoms and atom_name in native_residue.atoms
        ]
        if not common:
            raise ValueError(
                f"mapped residue lacks corresponding backbone atoms: "
                f"{native_residue.chain}:{native_residue.number}{native_residue.insertion}"
            )
        used_residues += 1
        for atom_name in common:
            moving.append(model_residue.atoms[atom_name].coord)
            fixed.append(native_residue.atoms[atom_name].coord)
    return moving, fixed, used_residues


def compute_capri_metrics(
    model_path: Path,
    native_path: Path,
    *,
    allowed_root: Path,
    model_receptor_chains: tuple[str, ...],
    model_ligand_chains: tuple[str, ...],
    native_receptor_chains: tuple[str, ...],
    native_ligand_chains: tuple[str, ...],
    chain_mapping: dict[str, str],
) -> CapriMetrics:
    """Compute reference-only CAPRI metrics with explicit semantic chain roles."""
    model = _parse_pdb(model_path, allowed_root)
    native = _parse_pdb(native_path, allowed_root)
    _validate_chain_mapping(
        model,
        native,
        model_receptor_chains=model_receptor_chains,
        model_ligand_chains=model_ligand_chains,
        native_receptor_chains=native_receptor_chains,
        native_ligand_chains=native_ligand_chains,
        chain_mapping=chain_mapping,
    )

    pairs_by_model_chain: dict[str, list[tuple[_Residue, _Residue]]] = {}
    unmapped: list[str] = []
    for model_chain, native_chain in chain_mapping.items():
        pairs, chain_unmapped = _align_residues(
            model.chains[model_chain], native.chains[native_chain]
        )
        pairs_by_model_chain[model_chain] = pairs
        unmapped.extend(chain_unmapped)

    native_receptor = [
        residue for chain in native_receptor_chains for residue in native.chains[chain]
    ]
    native_ligand = [
        residue for chain in native_ligand_chains for residue in native.chains[chain]
    ]
    native_contacts = _contacts(native_receptor, native_ligand, cutoff=5.0)
    if not native_contacts:
        raise ValueError("native reference has no 5 A receptor/ligand contacts")

    model_to_native_residue: dict[tuple[str, int, str, str], _Residue] = {}
    for pairs in pairs_by_model_chain.values():
        for model_residue, native_residue in pairs:
            model_to_native_residue[model_residue.key] = native_residue
    model_receptor = [
        residue
        for chain in model_receptor_chains
        for residue in model.chains[chain]
        if residue.key in model_to_native_residue
    ]
    model_ligand = [
        residue
        for chain in model_ligand_chains
        for residue in model.chains[chain]
        if residue.key in model_to_native_residue
    ]
    model_contacts_raw = _contacts(model_receptor, model_ligand, cutoff=5.0)
    model_contacts = {
        (
            model_to_native_residue[left].key,
            model_to_native_residue[right].key,
        )
        for left, right in model_contacts_raw
    }
    recovered = native_contacts & model_contacts
    fnat = len(recovered) / len(native_contacts)

    native_interface_pairs = _contacts(native_receptor, native_ligand, cutoff=10.0)
    if not native_interface_pairs:
        raise ValueError("native reference has no 10 A interface")
    native_interface = {
        residue_key for contact in native_interface_pairs for residue_key in contact
    }
    mapped_native_keys = {
        native_residue.key
        for pairs in pairs_by_model_chain.values()
        for _, native_residue in pairs
    }
    missing_interface = sorted(native_interface - mapped_native_keys)
    if missing_interface:
        raise ValueError(
            f"native interface contains {len(missing_interface)} unmapped residue(s)"
        )

    all_pairs = [
        pair for model_chain in chain_mapping for pair in pairs_by_model_chain[model_chain]
    ]
    interface_model, interface_native, interface_residues = _corresponding_backbone(
        all_pairs, native_subset=native_interface
    )
    _, _, i_rmsd = _kabsch(interface_model, interface_native)

    receptor_pairs = [
        pair
        for chain in model_receptor_chains
        for pair in pairs_by_model_chain[chain]
    ]
    ligand_pairs = [
        pair for chain in model_ligand_chains for pair in pairs_by_model_chain[chain]
    ]
    receptor_model, receptor_native, _ = _corresponding_backbone(receptor_pairs)
    rotation, translation, _ = _kabsch(receptor_model, receptor_native)
    ligand_model, ligand_native, _ = _corresponding_backbone(ligand_pairs)
    ligand_model_array = np.asarray(ligand_model, dtype=float)
    ligand_native_array = np.asarray(ligand_native, dtype=float)
    transformed_ligand = ligand_model_array @ rotation + translation
    l_rmsd = float(
        np.sqrt(
            np.mean(np.sum((transformed_ligand - ligand_native_array) ** 2, axis=1))
        )
    )
    if not all(math.isfinite(value) for value in (fnat, i_rmsd, l_rmsd)):
        raise ValueError("CAPRI metrics must be finite")
    if not 0.0 <= fnat <= 1.0 or i_rmsd < 0.0 or l_rmsd < 0.0:
        raise ValueError("CAPRI metrics are outside their valid ranges")
    return CapriMetrics(
        fnat=fnat,
        i_rmsd=i_rmsd,
        l_rmsd=l_rmsd,
        native_contact_count=len(native_contacts),
        recovered_native_contact_count=len(recovered),
        native_interface_residue_count=len(native_interface),
        interface_atom_count=len(interface_model),
        receptor_alignment_atom_count=len(receptor_model),
        ligand_rmsd_atom_count=len(ligand_model),
        unmapped_residues=sorted(unmapped),
        warnings=[*model.warnings, *native.warnings],
    )


def classify_capri_quality(
    fnat: float, i_rmsd: float, l_rmsd: float
) -> CapriCategoryResult:
    """Apply the traditional CAPRI criteria printed in the DockQ paper."""
    if not all(math.isfinite(value) for value in (fnat, i_rmsd, l_rmsd)):
        raise ValueError("CAPRI category inputs must be finite")
    if not 0.0 <= fnat <= 1.0 or i_rmsd < 0.0 or l_rmsd < 0.0:
        raise ValueError("CAPRI category inputs are outside their valid ranges")
    if fnat >= 0.5 and (l_rmsd <= 1.0 or i_rmsd <= 1.0):
        category, rule = "high", "fnat>=0.5 and (l_rmsd<=1 or i_rmsd<=1)"
    elif (
        (0.3 <= fnat < 0.5 and (l_rmsd <= 5.0 or i_rmsd <= 2.0))
        or (fnat >= 0.5 and l_rmsd > 1.0 and i_rmsd > 1.0)
    ):
        category, rule = "medium", (
            "(0.3<=fnat<0.5 and (l_rmsd<=5 or i_rmsd<=2)) or "
            "(fnat>=0.5 and l_rmsd>1 and i_rmsd>1)"
        )
    elif (
        (0.1 <= fnat < 0.3 and (l_rmsd <= 10.0 or i_rmsd <= 4.0))
        or (fnat >= 0.3 and l_rmsd > 5.0 and i_rmsd > 2.0)
    ):
        category, rule = "acceptable", (
            "(0.1<=fnat<0.3 and (l_rmsd<=10 or i_rmsd<=4)) or "
            "(fnat>=0.3 and l_rmsd>5 and i_rmsd>2)"
        )
    else:
        category, rule = "incorrect", "all remaining traditional CAPRI cases"
    return CapriCategoryResult(
        category=category,
        category_definition_id=CATEGORY_DEFINITION_ID,
        matched_rule=rule,
        fnat=fnat,
        i_rmsd=i_rmsd,
        l_rmsd=l_rmsd,
    )
