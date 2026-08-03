# Phase D4 — Docker Compose Live Local (End to End)

> 状态：**D4 verified** · 真实端到端验证完成（2026-08-03）

## 架构（固定）

```
宿主机 Labmate Python 3.11 CLI orchestrator
        ↓ 固定 CLI + 共享 volume
ColabFold GPU worker container（network_mode: none）
        ↓ rank-1 H/L PDB
LightDock CPU worker container
        ↓ poses
Labmate host-side validation / analysis / ranking / report / manifest / ZIP
```

- Labmate orchestrator 不在容器内
- 不向 Web 容器挂载 Docker socket
- 公开 Streamlit 仍为 Replay-only
- 不称为 fully containerized web application、Live Remote、production deployment

## 显式运行模式

| 模式 | 触发方式 | 说明 |
|---|---|---|
| `host`（默认） | 无参数或 `--tool-execution-provider host` | 用户安装的宿主工具；行为与 v0.3.0 完全一致 |
| `docker_compose` | `--tool-execution-provider docker_compose` + 三个路径参数 | 容器 worker；必须显式选择，无自动检测、无静默回退 |

旧 project.json（无 `tool_execution_provider` 字段）默认 `host`，完全向后兼容。
Replay、Benchmark Local、RFantibody design 不受影响。

### CLI 用法

```bash
python -m labmate.cli run project.json --mode live_local \
  --tool-execution-provider docker_compose \
  --docker-work-root runs/docker-live/work \
  --docker-data-root d:\colabfold-data\models \
  --docker-cache-root runs/docker-live/cache \
  --output runs/docker-live/runs
```

## 工作目录隔离

每次 run、每个 candidate 使用独立目录：

```
runs/docker-live/work/
  <candidate_id>/
    colabfold/
      input/     (只读 FASTA)
      output/    (可写, rank-1 PDB + score JSON)
    lightdock/
      inputs/    (receptor + ligand)
      outputs/   (GSO + poses)
```

候选间不共享可写输出目录。ColabFold rank-1 PDB 必须通过现有严格链映射/序列验证后，才复制为 LightDock ligand 输入。

## 真实验证（2026-08-03）

输入：`examples/live_local_smoke` 的 CC0 合成 1 candidate（VH 112aa + VL 110aa）。

参数：ColabFold 固定 D3 参数；LightDock 2 swarms / 10 glowworms / 10 steps / 2 poses。

### Run: `RUN-20260803-121251-784e9fd5`（修复后最终验证）

| 阶段 | 结果 | 内容 |
|---|---|---|
| S00–S03 | succeeded | 初始化/输入验证/序列 QC |
| S04 | succeeded | ColabFold GPU 容器预测（含容器启动） |
| S05 | succeeded | 链映射 + pLDDT 校验 |
| S06 | succeeded | LightDock CPU 容器 setup/run/generate |
| S07–S10 | succeeded | 界面分析/排名/报告/manifest/ZIP |
| S09 | skipped_optional | PyMOL |

（早期验证 run `RUN-20260803-113314-b2cd5ea1` 亦通过；本次为修复后的最终记录。）

### 验收项

| 检查项 | 结果 |
|---|---|
| 全部阶段实际执行（非 fixture 回放） | ✅ |
| ColabFold GPU 容器执行 | ✅（version 1.6.2 / jax gpu 记录于 manifest） |
| LightDock CPU 容器执行 | ✅（version 0.9.4 记录于 manifest） |
| rank-1 PDB 严格链序列匹配 | ✅ `exact_input_sequences_matched_to_colabfold_pdb: true` |
| pose-score 一一对应 | ✅ `explicit_selected_gso_line_to_lightdock_<line_index>.pdb` |
| candidate_ranking.csv 结构 | ✅ 29 列，final_score 完整 |
| interface_residues.csv | ✅ 存在 |
| report.html 离线可开 | ✅ |
| manifest 通过字段校验 | ✅ `tool_execution_provider: docker_compose`, `status: verified_live` |
| ZIP 无路径穿越 / 无空文件 | ✅ 35 entries 全部安全 |
| 日志无绝对路径/完整序列/secret | ✅ `privacy_audit_passed: true` |
| 网络禁用 | ✅ `network_mode: none`（single_sequence） |
| 无 fallback 到 host executable / Replay | ✅ 工具 provider 字段 = docker-compose workers |

### 关键产物 SHA-256（run `RUN-20260803-121251-784e9fd5`）

| 产物 | SHA-256 |
|---|---|
| candidate_ranking.csv | `423635b37b1d460221ac522fd29266b366afec214712ef8120d7556ea7419c16` |
| interface_residues.csv | `525e6582e43310ecf1a569952d0035cc2c5478b079a466b203ff58b0de0338f6` |
| report.html | `2202792f8be4144fcbcad0df7d1d28808ddca0f3b68753543935ced79861f0d8` |
| manifest.json | `2dca59b864c3b8e680aad8a433ad685d4f000f5e79c29ff86a58bb11048e23bd` |
| structures/…/colabfold/antibody_unrelaxed_rank_001_….pdb | `04d19163305b45a5503c8d32c3d78f6a60edd56723d17d7989a09bc5341f1351` |
| structures/…/colabfold/antibody_scores_rank_001_….json | `85b0483bf5968b65cf26fac914f424b8f36ad34ad344ec41cf7723aea85424c7` |
| structures/…/ranked_1.pdb（normalized） | `df3170b5a4f992d36c146224b19686e7d42e3518c0134007812fbaa558d12d4e` |
| docking/…/pose_001.pdb | `b9452ea13e0e66fc3d8a12942813a9ae394d2b0e91bc0fdb469a467f8236c138` |
| docking/…/pose_002.pdb | `4f6eea62e4d3017c37330dedfb0a61eea88f7b38a12cfeb323e665ce6926a063` |
| docking_scores.csv | `0317dc47b465f9d5d1e22aa6dbaeb0ddabe33f635c26bc6e9f2f7c108e233d81` |
| pose_score_mapping.csv | `1c27d61d83a79c475697ae6a39846f7c0d029acaa4c51b150680b13c398627a5` |
| Run ZIP | `RUN-20260803-121251-784e9fd5.zip`（188,668 bytes） |

**Score JSON 已作为正式 run artifact**：与 rank-1 PDB 按 prefix/rank/model tag 精确匹配复制到
`structures/<candidate_id>/colabfold/`，进入 S04 output hashes、manifest artifact 清单和 ZIP
（ZIP 条目 `structures/LIVE-SMOKE-001/colabfold/antibody_scores_rank_001_….json`）。

## Manifest / Provenance

Docker Compose 模式 manifest 记录：

- `tool_execution_provider: docker_compose`
- 工具 provider = `docker-compose colabfold worker` / `docker-compose lightdock worker`
- ColabFold 1.6.2 / LightDock 0.9.4 版本
- `network_policy: offline_single_sequence/runtime_network_disabled`
- `model_data_policy: user_mounted_preinstalled_only`
- 输入/输出 SHA-256、每阶段退出码与状态
- 不记录：用户名、主机名、Windows/WSL 绝对路径、模型数据绝对路径、token/secret、完整环境变量

## 测试（2026-08-03 修复后）

| 类型 | 结果 |
|---|---|
| D1 单元测试 | 26 passed |
| D3 单元测试（含 output_dir 契约） | 41 passed（1 skipped: Windows 无 symlink 特权） |
| D3 集成测试（真实 Docker + GPU + 权重 + entrypoint 校验） | 4 passed |
| D4 单元测试（含 host regression） | 14 passed |
| D4 集成测试（真实端到端） | 1 passed（91s） |
| host Live Local CLI 回归 | ✅ host 模式无 NameError；正确 fail-closed 报"缺少工具" |
| docker compose config | ✅ |
| py_compile / git diff --check | ✅ |
| repository-wide pytest | 164 passed / 1 skipped / 130 errors（0 failed）；130 errors 与 origin/main 完全一致（预存 Windows tmp_path 权限问题，已在干净 origin/main 复现），不标为通过 |

## 模型数据验证边界（修复后）

- **host provider**：继续验证 `job.tools.colabfold_args` 中唯一 `--data` 路径存在（fail closed）。
- **docker_compose provider**：不要求宿主机 ColabFold `--data` 路径存在；模型数据只由
  `ColabFoldContainerBackend` 对 `docker_data_root` 验证（5 个 multimer_v3 npz）。
  Docker 模式不回退到 host 路径。
- manifest `models.model_data_policy`：
  `preinstalled_only`（host）/ `user_mounted_preinstalled_only`（docker_compose）。
- S00 notes 按 provider 准确记录验证边界。

## 尚未覆盖

- 第三方机器复现（Phase D5）
- 镜像 registry 分发
- RFantibody 容器
- RF2 / IgCraft
- Live Remote
- 公共 Streamlit 计算
- 科学/实验验证
