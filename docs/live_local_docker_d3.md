# Phase D3 — ColabFold GPU Worker

> 状态：**D3 verified** · 真实 GPU 验证完成（2026-08-03）

## 环境

| 属性 | 值 |
|---|---|
| 基础镜像 | `ghcr.io/sokrypton/colabfold:1.6.2-cuda13` |
| 基础镜像 digest | `sha256:c9eab0253fe324b7ec2ec644607141539d7580a4e88d1d3788abba8c92d61ef1` |
| 本项目镜像 | `antibody-labmate-colabfold:1.6.2` |
| 镜像 ID | `6967f739bc8e` |
| 镜像大小 | 8.82 GB |
| 镜像 RepoDigest（本地构建） | `sha256:6967f739bc8eea481972645d233888d440d9f7f5861d6523eb757dce7cc97e33` |
| ColabFold | 1.6.2 (`alphafold-colabfold` 2.3.18) |
| JAX / jaxlib | 0.10.2（`jax-cuda13-pjrt` / `jax-cuda13-plugin`） |
| Python | 3.12.12（官方镜像自带） |
| OpenMM | 8.5.2（含 OpenMM-CUDA-13） |
| 容器用户 | `colabfold` uid 10002（非 root） |

## 宿主机 GPU 环境

| 属性 | 值 |
|---|---|
| GPU | NVIDIA GeForce RTX 5070 Ti Laptop GPU |
| 显存 | 12,227 MiB |
| 驱动 | 610.88 (CUDA UMD 13.3) |
| Compute capability | 12.0 (Blackwell) |
| Docker GPU passthrough | ✅ 已验证（`nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi` 成功） |
| Docker Engine / Compose | 29.6.2 / v5.3.1 |

## 模型数据挂载（只读）

- 宿主路径：用户提供的预装模型数据目录（验证时约 5.2 GB；以 `--docker-data-root` 传入）
- 容器路径：`/models/colabfold`（只读）
- 包含 5 个 `params_model_*_multimer_v3.npz`（各 ~355 MB）+ ptm/单链变体
- 启动前 adapter 验证全部 5 个 multimer_v3 参数文件存在

## 固定预测参数（不可被调用方覆盖）

```text
colabfold_batch INPUT_FASTA OUTPUT_DIR
--msa-mode single_sequence
--data /models/colabfold
--model-type alphafold2_multimer_v3
--num-models 1
--num-recycle 1
--num-relax 0
--random-seed 0
--disable-unified-memory
--compile-mode fast
```

与已验证的宿主机后端参数完全一致。`network_mode: none` —— `single_sequence` 模式无任何网络请求。

## 真实验证结果

### version / gpu-check

```text
colabfold 1.6.2
jax 0.10.2 backend gpu
NVIDIA GeForce RTX 5070 Ti Laptop GPU, 12227 MiB
jax gpu device: cuda:0
```

### predict smoke（CC0 synthetic VH/VL，非 test double）

输入：`live-local-smoke-run` 的 CC0 合成 VH (112 aa) + VL (110 aa)，单记录 `VH:VL` FASTA。

| 检查项 | 结果 |
|---|---|
| rank-1 PDB 生成 | ✅ `antibody_unrelaxed_rank_001_alphafold2_multimer_v3_model_1_seed_000.pdb` |
| PDB 大小 | 150,903 bytes（1,858 ATOM） |
| 链 | A + B 恰好两条 |
| VH 逐字符匹配 | ✅ 112/112 |
| VL 逐字符匹配 | ✅ 110/110 |
| 无 symlink | ✅ |
| 输出 SHA-256 | `249f9df8781e7626f778418316b6091ad094753675b662be5054f67b95c1c892` |
| 峰值显存 | 4,186 MiB（采样 32 次） |
| 首次运行时间 | 46.7 s（含 JAX 编译） |
| 二次运行时间 | 8.1 s（编译缓存复用） |
| 网络禁用 | ✅ `network_mode: none` 下完成 |
| 文本日志隐私 | ✅ 无宿主机绝对路径、无完整序列（`config.json` 的 `host_url` 为 ColabFold 未使用默认字段，与 LIVE_LOCAL_VALIDATION.md 记录一致） |

### 已记录限制

- JAX 在显存分配时出现 `CUDA_ERROR_OUT_OF_MEMORY` 降级日志（尝试分配 8.96 GiB 失败后自动回退）——与宿主机已验证记录行为一致；预测仍成功完成。
- 本 smoke 是软件集成验证，不是科学验证：pLDDT/pTM/ipTM 为合成序列结果，不代表结构准确性。

## 安全边界

- 仅 `colabfold` service 获得 GPU（compose `deploy.resources.reservations.devices`）
- `lightdock` service 继续 CPU-only
- 无 privileged、无 host network、无 Docker socket 挂载
- `network_mode: none`
- 根文件系统只读；`/tmp` (tmpfs)、`/work/output`、`/work/cache` 可写
- `cap_drop: ALL` + `no-new-privileges`
- 模型权重、数据库、用户序列、密钥均不写入镜像

## Entrypoint 白名单

| 子命令 | 说明 |
|---|---|
| `version` | 打印 colabfold + jax 版本与 backend |
| `gpu-check` | nvidia-smi + JAX GPU 设备验证 |
| `predict INPUT_FASTA OUTPUT_DIR` | 固定参数预测；FASTA 校验（单记录、VH:VL 两链、标准氨基酸、≤20KB、无路径穿越） |

拒绝：`/`、`\`、`..`、绝对路径、额外位置参数、未知参数、覆盖固定科学参数的参数、符号链接、超大 FASTA、非法氨基酸、非两链格式、空序列、第三链、**缺失 `:` 分隔符（entrypoint 在拆分 VH/VL 前显式检查 `[[ "$seq" == *:* ]]`）**。

### Python adapter output_dir 契约（修复后）

`ColabFoldContainerBackend.predict` 的 `output_dir` 必须：
- 严格位于 `<work_root>/output` 之下（越界拒绝）；
- 单层安全 basename 子目录（嵌套拒绝）；
- 不存在或存在但为空（非空拒绝，禁止复用陈旧结果）；
- 非 symlink；
- 容器内实际使用 `output_dir.name` 作为 predict OUTPUT_DIR，输出发现使用同一真实目录。

rank-1 score JSON 按 `_COLABFOLD_PDB_NAME` 解析的 prefix/rank/model tag 精确匹配
（`<prefix>_scores_rank_<NNN>_<tag>.json`），缺失、多匹配、无效 JSON 均 fail closed；
不采用"任意第一个 scores JSON"模糊 fallback。

## 测试

| 类型 | 结果 |
|---|---|
| D3 单元测试 | 29 passed |
| D3 集成测试（真实 Docker + GPU） | 见下方 |

集成测试 `test_version_and_gpu_check` / `test_predict_produces_rank1_pdb` 在 D3 验证过程中已以真实容器运行（version/gpu-check/predict 均真实执行）。
