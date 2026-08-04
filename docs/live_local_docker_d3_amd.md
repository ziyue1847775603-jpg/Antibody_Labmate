# Phase D3 — ColabFold GPU Worker (AMD/ROCm)

> 状态：**implemented · AMD hardware verification pending**

## 与 NVIDIA 版本的关系

AMD/ROCm ColabFold worker 是 NVIDIA CUDA worker 的逻辑等价实现。
两者共享：

- 相同的 `ColabFoldContainerBackend` Python adapter（GPU 厂商无关）
- 相同的 `DockerComposeExecutors` 和 `execute_live_local` 入口
- 相同的固定预测参数（`single_sequence` / `multimer_v3` / 1 model /
  1 recycle / 0 relaxation）
- 相同的 LightDock CPU worker
- 相同的 `--tool-execution-provider docker_compose` CLI opt-in 模式

差异仅在容器层：

| 组件 | NVIDIA (CUDA) | AMD (ROCm) |
|---|---|---|
| Compose 文件 | `docker-compose.live-local.yml` | `docker-compose.live-local-amd.yml` |
| 基础镜像 | `ghcr.io/sokrypton/colabfold:1.6.2-cuda13` | `rocm/jax-community:latest` |
| GPU 设备 | `deploy.resources.reservations.devices: driver nvidia` | `devices: /dev/kfd, /dev/dri; group_add: video` |
| GPU 监控 | `nvidia-smi` | `rocm-smi` |
| JAX backend | `jax-cuda13-pjrt` | `jax[rocm]` (由基础镜像提供) |
| OpenMM | `OpenMM-CUDA-13` | CPU-only OpenMM (ROCm 无 OpenMM GPU 后端) |

## 环境

| 属性 | 值 |
|---|---|
| 基础镜像 | `rocm/jax-community:latest`（digest: 首次构建后记录） |
| 项目镜像 | `antibody-labmate-colabfold-amd:1.6.2` |
| ColabFold | 1.6.2 (`alphafold-colabfold` 2.3.18) |
| JAX | 由基础镜像提供（ROCm backend） |
| Python | 由基础镜像提供 |
| OpenMM | CPU-only（ROCm 无 GPU 加速 OpenMM） |
| 容器用户 | `colabfold` uid 10003（非 root） |

## 模型数据挂载（只读）

与 NVIDIA 版本完全相同：
- 宿主路径：用户提供的预装模型数据目录（以 `--docker-data-root` 传入）
- 容器路径：`/models/colabfold`（只读）
- 包含 5 个 `params_model_*_multimer_v3.npz`
- 启动前 adapter 验证全部 5 个 multimer_v3 参数文件存在

## Entrypoint 白名单

| 子命令 | 说明 |
|---|---|
| `version` | 打印 colabfold + jax 版本与 backend（`rocm`） |
| `gpu-check` | rocm-smi + JAX RocmDevice 验证 |
| `predict INPUT_FASTA OUTPUT_DIR` | 固定参数预测（与 NVIDIA 版本 **完全相同**） |

## CLI 用法

```bash
python -m labmate.cli run project.json --mode live_local \
  --tool-execution-provider docker_compose \
  --docker-compose-file docker-compose.live-local-amd.yml \
  --docker-work-root runs/docker-live/work \
  --docker-data-root /path/to/preinstalled-colabfold-models \
  --docker-cache-root runs/docker-live/cache \
  --output runs/docker-live/runs
```

与 NVIDIA 版本的唯一差异：`--docker-compose-file docker-compose.live-local-amd.yml`。

## AMD 宿主前置条件

- AMD ROCm 驱动已安装（`rocm-smi` 可在宿主执行）
- Docker 已运行，`/dev/kfd` 和 `/dev/dri` 设备可访问
- `rocm/jax-community:latest` 镜像已拉取
- 预装 AlphaFold multimer_v3 模型权重（与 NVIDIA 版本相同）
- **不需要** NVIDIA Container Toolkit 或 CUDA 驱动

## AMD 硬件验证状态

**pending** — 本分支尚未在真实 AMD GPU 硬件上运行。

计划验证项：
- `docker compose -f docker-compose.live-local-amd.yml run --rm colabfold version` → colabfold 1.6.2, jax backend rocm
- `docker compose -f docker-compose.live-local-amd.yml run --rm colabfold gpu-check` → rocm-smi OK, JAX RocmDevice
- `docker compose -f docker-compose.live-local-amd.yml run --rm colabfold predict ...` → rank-1 PDB, VH/VL exact match
- 端到端 Docker Compose Live Local AMD smoke（D4）

## 已知限制

- **OpenMM 无 ROCm GPU 加速**：AMD 环境下 OpenMM 回退 CPU 模式；不影响 ColabFold 结构预测
  （OpenMM 仅用于可选的 AMBER 能量最小化，而本 worker 设置 `--num-relax 0` 跳过之）
- **JAX/ROCm 版本兼容性**：`rocm/jax-community:latest` 跟随上游，实施时应锁定 digest
- **非官方 ColabFold 镜像**：无上游 ROCm ColabFold 镜像，本 worker 在 ROCm JAX 基础上 pip 安装 ColabFold

## 安全边界

与 NVIDIA 版本相同：
- 仅 `colabfold` service 获得 GPU 设备
- `lightdock` service 继续 CPU-only
- 无 privileged、无 host network、无 Docker socket 挂载
- `network_mode: none`
- 根文件系统只读；`/tmp` (tmpfs)、`/work/output`、`/work/cache` 可写
- `cap_drop: ALL` + `no-new-privileges`
- 模型权重、数据库、用户序列、密钥均不写入镜像
