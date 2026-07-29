from __future__ import annotations
import hashlib
from pathlib import Path
import pytest
from labmate.backends.base import PredictionResult
from labmate.prediction_artifact import docking_input, prediction_artifact

_AA={"A":"ALA","C":"CYS","D":"ASP","E":"GLU","F":"PHE","G":"GLY","H":"HIS","I":"ILE"}
def _pdb(path: Path, chains: dict[str,str]) -> None:
    rows=[]; n=1
    for chain, seq in chains.items():
        for i, aa in enumerate(seq,1):
            rows.append(f"ATOM  {n:5d}  CA  {_AA[aa]:>3s} {chain}{i:4d}    {float(n):8.3f}{0.:8.3f}{0.:8.3f}{1.:6.2f}{20.:6.2f}           C  "); n+=1
    path.write_text("\n".join(rows)+"\nEND\n",encoding="utf-8")
def _result(path: Path) -> PredictionResult:
    return PredictionResult(pdb_path=path,backend_name="igfold",status="succeeded",metadata={"native_metrics":{"prmsd":{"shape":[1,8,4]}},"native_metrics_semantics":"backend_native_unscaled"})
def test_artifact_and_docking_input_are_backend_neutral_and_hash_checked(tmp_path: Path)->None:
    pdb=tmp_path/"antibody.pdb"; antigen=tmp_path/"antigen.pdb"; _pdb(pdb,{"H":"ACDE","L":"FGHI"}); _pdb(antigen,{"A":"ACDE"})
    artifact=prediction_artifact(_result(pdb),heavy_chain="ACDE",light_chain="FGHI",allowed_root=tmp_path)
    assert artifact.chain_map=={"heavy":"H","light":"L"}; assert artifact.native_metrics_semantics=="backend_native_unscaled"
    handoff=docking_input(artifact,antigen_pdb=antigen,allowed_root=tmp_path,output_root=tmp_path/"handoff")
    assert handoff.receptor_role=="antigen" and handoff.ligand_role=="antibody" and handoff.antigen_chains==["A"]
    pdb.write_text("tampered",encoding="utf-8")
    with pytest.raises(ValueError,match="hash mismatch"): docking_input(artifact,antigen_pdb=antigen,allowed_root=tmp_path,output_root=tmp_path/"second")
@pytest.mark.parametrize("kind",["symlink","extra","mismatch","html"])
def test_adapter_rejects_unsafe_or_ambiguous_prediction(kind:str,tmp_path:Path)->None:
    pdb=tmp_path/"antibody.pdb"; _pdb(pdb,{"H":"ACDE","L":"FGHI"})
    if kind=="symlink":
        target=tmp_path/"target.pdb"; _pdb(target,{"H":"ACDE","L":"FGHI"}); pdb.unlink(); pdb.symlink_to(target)
    elif kind=="extra": _pdb(pdb,{"H":"ACDE","L":"FGHI","X":"ACDE"})
    elif kind=="mismatch": _pdb(pdb,{"H":"ACDE","L":"FGHH"})
    else: pdb.write_text("<html>error</html>",encoding="utf-8")
    with pytest.raises(ValueError): prediction_artifact(_result(pdb),heavy_chain="ACDE",light_chain="FGHI",allowed_root=tmp_path)
