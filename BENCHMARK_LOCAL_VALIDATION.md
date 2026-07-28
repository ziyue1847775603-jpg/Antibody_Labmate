# Phase 2b Benchmark Local validation

- Date: 2026-07-28
- Validation type: **synthetic software-integration smoke**
- Capability status: **`implemented_unverified`**

This record covers one real execution of the separately installed LightDock
0.9.4 toolchain through `benchmark_local`. It proves that the local software
integration can run on the project-authored CC0 synthetic inputs. It is **not a
DB5.5 scientific benchmark**, **not affinity or experimental validation**, and
does not establish binding, binding free energy, specificity, safety, efficacy,
or scientific quality.

## Repository and runtime scope

- Branch: `benchmark-local`
- Comparison baseline: `04834a136c1d74f76a4bd1dd9ebd1d8acee34fa2`
- Final run ID: `BENCH-20260728-102641-421ef42c`
- Start: `2026-07-28T10:26:40Z`
- End: `2026-07-28T10:26:56Z`
- CLI exit code: `0`
- Network used by Antibody Labmate: `false`
- ColabFold invoked: `false`
- Project Python invocation: `$PROJECT_ROOT/.venv311/bin/python`
- Project Python version: `3.11.15`
- LightDock environment Python: `$LIGHTDOCK_ROOT/bin/python3.11`
- LightDock environment Python version: `3.11.15`

For this public record, `$PROJECT_ROOT` denotes the repository root and
`$LIGHTDOCK_ROOT` denotes the local root of the separately installed LightDock
0.9.4 environment used by the smoke. The real external executable locations,
normalized only to remove machine-specific directory prefixes, were:

```text
$LIGHTDOCK_ROOT/bin/lightdock3_setup.py
$LIGHTDOCK_ROOT/bin/lightdock3.py
$LIGHTDOCK_ROOT/bin/lgd_generate_conformations.py
$LIGHTDOCK_ROOT/bin/lgd_cluster_bsas.py
```

`lightdock3.py -v` returned `lightdock3 0.9.4`. The setup, simulation, and
conformation-generation programs were executed. The cluster executable was
checked for existence and executability but was not invoked, so clustering did
not replace the raw declared score order.

## Inputs and parameters

The three inputs are project-authored synthetic PDB files dedicated under
CC0-1.0. They have no biological meaning.

| Input | SHA-256 |
|---|---|
| `examples/benchmark_local/antibody.pdb` | `b6cdabd02b6e1b46e0d1212896808a3568b6a324a9e7ea599fa8e9ce8a7ebf1b` |
| `examples/benchmark_local/antigen.pdb` | `9bad55ec619817f3b9495f553a7af2d6881a8d7701300300e0e781e8531f61b6` |
| `examples/benchmark_local/reference_complex.pdb` | `9a4dcca463d56eca04339c8643d53d9dfc0f829bdb16ddf0e059e4c204a884fa` |

Parameters:

```text
steps=20
swarms=4
glowworms=50
cores=1
top_poses=3
score_name=LightDock_0.9.4_fastdfire
score_direction=higher_is_better
random_seed_recording=manifest_only_external_lightdock_cli
```

The exact command was:

```bash
cd "$PROJECT_ROOT"
.venv311/bin/python -m labmate.cli run \
  runs/benchmark-local-validation-input/project.json \
  --mode benchmark_local \
  --output runs/benchmark-local-validation-output
```

The copied project file differed from
`examples/benchmark_local/project.json` only by confirming rights and replacing
the four executable placeholders with the paths recorded above. Inputs and
outputs were under the Git-ignored `runs/` directory.

## Independent result checks

- All three real external commands returned zero. Recorded elapsed times were
  3.83 s for setup, 4.65 s for simulation, and 4.13 s for conformation
  generation.
- `swarm_0` through `swarm_3` each contained exactly 50 non-comment rows in
  `gso_20.out` (200 final solutions total).
- Higher-is-better sorting produced:

  1. swarm 0, zero-based GSO row/glowworm 21, score `5.01219805`;
  2. swarm 0, row/glowworm 46, score `5.01131840`;
  3. swarm 0, row/glowworm 37, score `5.01043665`.

- The three exact source rows were written to `selected_top_poses.gso` in that
  order. Its zero-based line indices mapped byte-for-byte to
  `lightdock_0.pdb`, `lightdock_1.pdb`, and `lightdock_2.pdb`, then to
  `top_poses/pose_001.pdb` through `pose_003.pdb`. Filename sorting was not used
  to infer scores.
- Every generated pose contained exactly chains `A/H/L`, all 52 expected atoms,
  and the exact normalized residue number, insertion code, residue name, and
  atom name keys from the receptor and ligand inputs.
- `benchmark_metrics.csv` contained three score-ranked rows.
  `case_summary.csv` recomputed Top 1/5/10 from the corresponding ranked
  prefixes, not from a global best outside each prefix.
- The report was self-contained, retained valid `lang` and CSS attributes, used
  Jinja autoescaping, and contained the fixed computational-only disclaimers.
- Manifest artifact sizes and hashes were independently recomputed. The run ZIP
  contained exactly the same 49 files as the run directory, with no duplicate
  or unsafe entry and byte-for-byte identical content.
- Binary and text scans found no repository/output absolute path, home path,
  username, hostname, token shape, secret assignment, or environment
  assignment in the run artifacts or ZIP.

## Complete final artifact inventory

The ZIP SHA-256 is
`1d0a055f735a132938b6fef09f8585c2ba0a0df8679bccc5abcc0ef02d1c1135`.

| Relative artifact | Bytes | SHA-256 |
|---|---:|---|
| `benchmark_metrics.csv` | 1095 | `4149ebc7fd9f85411a6dfe34607ff529e538a5382a6d684a1ea2748c8a8c1200` |
| `case_summary.csv` | 245 | `35d70f8ef72a0e2ff58acec167bf59a0caa6391ea91b0e17a6956f05621b699a` |
| `inputs/antibody_normalized.pdb` | 2600 | `74f27c8e0de8ee3ae347106ea4156751387323d591065662f0a08d018e966cf1` |
| `inputs/antibody_original.pdb` | 2536 | `b6cdabd02b6e1b46e0d1212896808a3568b6a324a9e7ea599fa8e9ce8a7ebf1b` |
| `inputs/antigen_normalized.pdb` | 1628 | `588ab66179c201a8fd9822968005ceba428e82fb44476390623604c1c3a17ad6` |
| `inputs/antigen_original.pdb` | 1588 | `9bad55ec619817f3b9495f553a7af2d6881a8d7701300300e0e781e8531f61b6` |
| `inputs/reference_normalized.pdb` | 4220 | `b8a0d6a3effad6777e1bce8b5872964ef0d9346b4b8d048bddcab1dad483ac57` |
| `inputs/reference_original.pdb` | 4116 | `9a4dcca463d56eca04339c8643d53d9dfc0f829bdb16ddf0e059e4c204a884fa` |
| `interface_residues.csv` | 171 | `c47cc4b7a1cee5ec2b285e52e67560613f018fcfe6c1cb58754f5e438999aa3e` |
| `job.json` | 1018 | `693624a737a873e8488cd7f9fb7533f9d867bbe67758e09d6320778f6d05f32c` |
| `logs/benchmark_local.log` | 7876 | `71cbd123f6083e0f8408bbc87962a2350dee04a12165b44f1e90cbb02bda9032` |
| `logs/commands.json` | 8441 | `8ea5d1cafcdc7b97b4a1953a8e0f08698eea781b149a86a9ffd34df8a11d03f8` |
| `logs/pymol.txt` | 41 | `f8af8c75cd2fddd23c5cc73526924c9773b953affd39e0482864b23b3259ed93` |
| `manifest.json` | 33286 | `4a9c99210462f501c884e760a7de442770bb8345d57f278ef04bca99d1b2e960` |
| `manifest.sha256` | 80 | `f388789b3e250d0490eb7d1a417d857ac709f09c7420b480fa943a91ba85e772` |
| `poses.csv` | 1237 | `457f2a54254085d16e6bb9360ab774726f444b1c26d92cf5734e72002181a628` |
| `report.html` | 4287 | `1492cc52c11be46ebbbd467d8309d3943c92b229f6cdfa10cc293f8ab8d8b5d2` |
| `top_poses/pose_001.pdb` | 4108 | `535b5134085db18cb112f8546aa29f1e095bcc81b449f9028e1b63f5aeb9c378` |
| `top_poses/pose_002.pdb` | 4108 | `669556f307b8b746efa240e598503a543a1a1d3c5b21b75fb25aa116ce559d6e` |
| `top_poses/pose_003.pdb` | 4108 | `3ad85cbe8403deb877f77276547e4619919b335f4e3c87f65751cddb744071fb` |
| `work/antibody_receptor.pdb` | 2600 | `74f27c8e0de8ee3ae347106ea4156751387323d591065662f0a08d018e966cf1` |
| `work/antigen_ligand.pdb` | 1628 | `588ab66179c201a8fd9822968005ceba428e82fb44476390623604c1c3a17ad6` |
| `work/init/initial_positions_0.dat` | 4453 | `f181ae578076ef6072b6f3102b65ba72a52cd08202edcd22937cb6a6aef77ca0` |
| `work/init/initial_positions_1.dat` | 4393 | `f4efb70fd81f0f12b24b891cbafd8e67450dec84aab2d28bea2fb19c4a207142` |
| `work/init/initial_positions_2.dat` | 4367 | `3231109f5e45a8f4506bab7622e57a00e1ad6533da7751198600a9c84931f0ae` |
| `work/init/initial_positions_3.dat` | 4403 | `f67f94402b18ab3340a0608b18bcb82fb77837f915fce148920c71268f39f108` |
| `work/init/swarm_centers.pdb` | 316 | `7ec039e88f3c7bfd04d6d8298d93791faa1450eeeea04f2c61f2671ab1320666` |
| `work/lightdock.info` | 1112 | `ee043dbab50e7695234dae7ab6656b9c53f28a0f9c986ffe2c0084276d496a61` |
| `work/lightdock_0.pdb` | 4108 | `535b5134085db18cb112f8546aa29f1e095bcc81b449f9028e1b63f5aeb9c378` |
| `work/lightdock_1.pdb` | 4108 | `669556f307b8b746efa240e598503a543a1a1d3c5b21b75fb25aa116ce559d6e` |
| `work/lightdock_2.pdb` | 4108 | `3ad85cbe8403deb877f77276547e4619919b335f4e3c87f65751cddb744071fb` |
| `work/lightdock_antibody_receptor.pdb` | 2528 | `a614e6de59a23ae3493b3efa464b995a7464b33cfb20bd44f48886bf0c6af173` |
| `work/lightdock_antibody_receptor_mask.npy` | 160 | `622f786098ea98e73edd0e8b87f526522a172ac8860650d978648716e8f52130` |
| `work/lightdock_antigen_ligand.pdb` | 1580 | `b4c2bb7762307967ef1b69c8a2022e9a241a7112031c45e897ae3a66e2deb56a` |
| `work/lightdock_antigen_ligand_mask.npy` | 148 | `3c7c9bbbcd37f23196f30266e20ba741cb53b32ec21f4cd220e378d01619ad8f` |
| `work/selected_top_poses.gso` | 392 | `fa63366eee87364f66f8ae7c5eb7ee2524cef02099698a29a2f9632ea0d6f718` |
| `work/setup.json` | 682 | `d06fd2019c0bf820f487c3f0ce57d744ee9102482f8ea15db1ee8cacf6413fff` |
| `work/swarm_0/gso_0.out` | 6602 | `4e777fbda6ed1c5c9c6e284fc4e1788803526a7a530f1b6bf7dcc597952b6c89` |
| `work/swarm_0/gso_10.out` | 6598 | `df4259e97ff815e846ebc87b73683c520067dc790abc9ca7b3151593a60a98fb` |
| `work/swarm_0/gso_20.out` | 6599 | `97d3494573b7a11364e581be764f5ea38e4bd2524c27661596ca300512000442` |
| `work/swarm_1/gso_0.out` | 6599 | `c4d058f051be4bad1a99c02a671f0c7c8e2bbb11f74bea417491f50f97ab99f9` |
| `work/swarm_1/gso_10.out` | 6599 | `a9e6e5d79504acd6e57e87206cb218d4924fce8eccb58f79fc501669824a6bcc` |
| `work/swarm_1/gso_20.out` | 6599 | `a15669c6b6def439e4a666c55b5cf19fcfb8d8e5a46f1067b66a5a9947acbe5a` |
| `work/swarm_2/gso_0.out` | 6582 | `5baac0fab0607aef5e5bfb5dbfb7f5d25b34c46096a85f65253d5765dc49df94` |
| `work/swarm_2/gso_10.out` | 6580 | `b94375cbd34eb879befe90654ed8cf7923ec105526f503d4e427e77de15365c2` |
| `work/swarm_2/gso_20.out` | 6580 | `1f419530d42b296fc09e1944554b2fc5273e78b296624251b8e4666c4fe7365b` |
| `work/swarm_3/gso_0.out` | 6608 | `053e91afb8845608e24ab28f7fdb51e2642ae2273cc97f691406b9a7aa9c7c02` |
| `work/swarm_3/gso_10.out` | 6604 | `c66b3d09a4918b67f3963b08968dd6dbf44d72f9b84abee0911b58c1994b9e86` |
| `work/swarm_3/gso_20.out` | 6601 | `c1eef92627bdf7aacef335afcd9048eda9cb47aaad359a4baef782fb3e8afc30` |

## Failures discovered during validation

1. The original CA-only example PDBs produced no receptor surface selection in
   the real LightDock/ProDy setup and failed closed before simulation. The
   project-authored CC0 inputs were replaced with small standard-residue
   N/CA/C/O structures; strict chain/reference tests were added.
2. Environment-assignment redaction initially treated HTML `lang=` and CSS
   `display:` as environment variables. The rule was restricted to complete
   line-oriented assignments, and a regression test now protects valid HTML
   attributes and CSS.
3. Validation provenance initially hard-coded
   `real_external_lightdock_smoke_completed=false`. The manifest now records
   the completed synthetic integration separately from
   `scientific_validation_completed=false`.

These fixes were applied to source and the full real smoke was rerun. No output
from the failed or intermediate run was edited or presented as the final run.

## Remaining validation boundary

Still not completed:

- any real DB5.5 case or another curated antibody–antigen benchmark;
- scientific success-rate, ranking-quality, affinity, or experimental
  validation;
- other LightDock versions or scoring functions;
- performance, scale, cross-machine reproducibility, or deterministic replay;
- Schrödinger/PIPER comparison.

The capability therefore remains **`implemented_unverified`**.
