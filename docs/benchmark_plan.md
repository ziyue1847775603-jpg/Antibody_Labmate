# Public antibody-antigen docking benchmark plan

Stage 1 validates case manifests and separation of unbound docking inputs from
bound evaluation references. Stage 2 will be a fixed-parameter, three-case
pilot only after public provenance, licensing, chain mapping and data integrity
have been independently reviewed. Stage 3 is the full public
antibody-antigen subset.

The intended dataset candidate is the public antibody-antigen benchmark added
to Docking Benchmark 5.5, described by Ambrosetti et al. (2020) and linked by
the Pierce Lab antibody benchmark project. No dataset is downloaded or bundled
here; license and exact case metadata must be recorded in each manifest before
a pilot.

Docking consumes only unbound antibody/antigen inputs. The bound complex is
frozen until pose output hashes are complete, then used only for Fnat, I-RMSD
and L-RMSD evaluation. All pilot cases must share LightDock version, scoring
function, seed policy, swarms, glowworms and GSO steps. No per-case tuning is
permitted. Tool-native pose order is retained; prediction confidence is not a
ranking input.

Stage 1 now includes the versioned `capri_dockq_2016_v1` implementation,
traditional CAPRI category boundary tests, official DockQ numerical
cross-validation, and cross-swarm multi-pose provenance. A public DB5.5 pilot
has not yet been run. A small pilot cannot establish general scientific
validity, affinity, experimental binding, or therapeutic relevance.
