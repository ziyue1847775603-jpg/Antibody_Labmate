# Live Local Docker 化可行性审计

> 状态：草案 · 仅调查与设计 · 未实施

## 1. 当前 Live Local 真实调用链

基于 [labmate/live_local.py](../labmate/live_local.py) 的 `execute_live_local()` 函数（自 origin/main，commit `5107973`）：

```
ColabFold（AlphaFold2-based）→ LightDock
```

**各阶段详解：**

| 阶段 | 工具 | 方式 | 输入 | 输出 |
|---|---|---|---|---|
| S04 | ColabFold 1.6.2 | `subprocess.run([colabfold_batch, ...])` | VH/VL FASTA | rank_001 PDB，score JSON |
| S06 | LightDock 0.9.4 | `subprocess.run([lightdock3_setup.py, lightdock3.py, lgd_generate_conformations.py, ...])` | Antigen PDB (A chain) + ColabFold PDB (H/L chains) | GSO scores, PDB poses |

**不在 Live Local 主流程中的工具：**

- **RFantibody / RFdiffusion / ProteinMPNN**：独立的 `labmate design` CLI，VHH-only，与 Live Local 分开运行。通过外部 Python interpreter + subprocess 调用官方 RFantibody 脚本。
- **RF2（RoseTTAFold2）**：官方 RFantibody 流程的第三阶段（复合物预测/筛选），Antibody Labmate 代码库中 **完全未集成、未调用**。
- **IgCraft**：`audited_not_integrated`，接口不兼容（要求完整 PDB，非六条 CDR）。
- **IgFold**：独立 prediction-only backend，使用隔离的 Python 3.10 worker。

**ColabFold 的角色确认：** ColabFold 是 Live Local 主流程中 **唯一的结构预测后端**，不是可选复核或旧流程遗留。MSA 模式固定为 `single_sequence`，不访问公共 MSA 服务。

**LightDock 输入来源：** ColabFold 生成的 `ranked_1.pdb`（经链重映射为 H/L）作为配体，经清洗的 antigen PDB（重映射为 A 链）作为受体。

## 2. 工具环境兼容性矩阵

### 2.1 各工具需求汇总

> **注意：** 下表列出的 Python、CUDA 和依赖版本是 Antibody Labmate 当前拟采用
> 或已验证的固定环境，**不代表上游工具永久或唯一要求**。RFantibody 官方要求是
> CUDA 11.8+，若项目固定到具体镜像需另行记录 digest。ColabFold 的 Python/CUDA
> 要求随版本、JAX 和镜像变化，实施时必须锁定镜像 tag + digest。不要把 Python
> 3.10 或 CUDA 12.1+ 写成所有版本的绝对要求。

| 维度 | Antibody Labmate | RFantibody 官方 | ColabFold 1.6.2 | LightDock 0.9.4 |
|---|---|---|---|---|
| **Python** | **3.11** (>=3.11,<3.13) — 当前 orchestrator 固定版本 | **3.10** — RFantibody 官方 Docker/uv 环境默认 | **3.10** (conda) — 当前项目 ColabFold 验证环境记录 | 3.x（3.6+，当前项目验证 3.11 可用） |
| **ML 框架** | 无（仅 stdlib + Jinja2/Pydantic/Streamlit） | **PyTorch** (CUDA 11.8) — 官方 Docker 基础镜像 | **JAX** — 实际 CUDA 版本取决于 JAX wheel 和镜像 tag | 无 GPU 依赖 |
| **CUDA** | 不需要 | **11.8** — 官方 Docker 基础镜像；官方最低要求为 11.8+ | 验证环境使用 CUDA 12.1+；新版本可能不同 | 不需要 |
| **cuDNN** | 不需要 | 8 (含于官方基础镜像) | 随 JAX/CUDA 版本锁定 | 不需要 |
| **GPU 需求** | 不需要 | **必须** (NVIDIA) | **必须**（Ampere SM 8.0+ 可选 Pallas 加速） | 不需要 |
| **基础 OS** | Debian slim (Python 3.11-slim) | Ubuntu 22.04（官方 Docker 基础） | Ubuntu 22.04 | 任意 Linux |
| **特殊依赖** | 无 | DGL (CUDA custom build), e3nn, USalign | HH-suite, Kalign, MMseqs2, OpenMM, PDBFixer | NumPy, SciPy, Cython, BioPython, MPI4py, ProDy |
| **模型权重** | 无 | `RFdiffusion_Ab.pt` (~1.7 GB), `ProteinMPNN_v48_noise_0.2.pt` | `params_model_*_multimer_v3.npz` ×5 (~10 GB) | 无 |
| **数据库** | 无 | 无 | MMseqs2/UniRef 等（仅 MSA-backed 模式需要；`single_sequence` 模式不需要） | 无 |
| **官方 Docker** | 现有 Replay-only Dockerfile | **是** — `nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04`，Apptainer `.sif` ~8 GB | **社区有** — `jysgro/colabfold` (~16.2 GB)；上游 ColabFold 有 CUDA 12/13 镜像 | **无** |
| **许可证** | MIT | MIT（code）；模型权重条款需用户自行审核 | MIT（code）；AlphaFold 模型/数据条款需单独审核 | **GPL-3.0** |
| **可再分发** | MIT 源码可 | 源码 MIT 可；权重需用户自行下载 | 源码 MIT 可；权重需用户自行下载 | GPL-3.0：分发时需保留许可证、来源和适用的源代码义务 |

### 2.2 关键依赖冲突

> 以下冲突基于当前拟采用或已验证的固定环境。若上游工具发布新版本（例如
> ColabFold 支持 Python 3.11 或 RFantibody 升级 CUDA 基础镜像），部分冲突
> 可能缓解。实施时应以锁定的镜像 tag + digest 为准。

| 冲突 | 严重程度 | 说明 |
|---|---|---|
| **Python 3.10 vs 3.11** | 高 | 当前 RFantibody 官方 Docker 默认 Python 3.10；当前项目 ColabFold 验证环境使用 Python 3.10 (conda)；Labmate orchestrator 使用 Python 3.11。当前三者无法共用一个 Python 环境。 |
| **CUDA 11.8 vs 12.1+** | 高 | RFantibody 官方 Docker 基础镜像使用 CUDA 11.8；当前项目 ColabFold 验证环境使用 CUDA 12.1+。不同 CUDA major 版本不能在同一容器内共存。 |
| **PyTorch vs JAX** | 中 | 若分容器部署则无冲突。同一容器内同时安装会增加镜像体积和依赖复杂度。 |
| **LightDock GPL-3.0 vs MIT** | 中 | LightDock 保持为独立安装和独立进程，通过命令行、退出码和普通文件产物与 Labmate 通信。独立容器主要用于依赖隔离、版本固定和许可证告知清晰度。容器边界本身不自动决定两个程序是否构成单一作品。分发时必须保留 LightDock 的许可证、来源和适用的源代码义务。本文不是法律意见，如公开分发整套镜像或紧密集成，应进一步审查许可证义务。 |
| **DGL CUDA custom build** | 高 | RFantibody 需要 DGL 的 CUDA 定制编译版本；标准 pip 安装可能不可用。需匹配具体 CUDA 版本的构建。 |
| **ColabFold RAM 需求** | 高 | 社区报告 80-96 GB RAM；单容器部署可能需要极高资源配置，不利于本地开发机。 |
| **ColabFold disk 需求** | 高 | 若不挂载数据库则只需权重 (~10 GB)；若启用 MSA 模式则需 80-180 GB。当前验证只使用 `single_sequence`，无需数据库。 |

## 3. 单容器 vs 多容器比较

### 3.1 单容器方案（一个巨型镜像）

**优点：**
- 部署简单（单一 `docker run`）
- 无跨容器通信开销

**缺点：**
- Python 版本差异 —— 当前 RFantibody 和 ColabFold 验证环境使用 Python 3.10，Labmate orchestrator 使用 3.11；同一容器内必须选择单一 Python 版本，可能需要 patch
- CUDA 版本差异 —— RFantibody 官方基础镜像使用 CUDA 11.8，当前 ColabFold 验证环境使用 CUDA 12.1+；同一容器只能使用一种 CUDA 基础镜像
- PyTorch + JAX 共存 —— 镜像体积巨大（估计 >30 GB）
- 许可证告知不清 —— 单一镜像模糊了各组件各自的许可证边界，不利于分发时履行告知义务
- 无法独立扩缩 GPU 资源（ColabFold 需要大量显存，RFantibody 次之，LightDock 不需要 GPU）
- 构建时间长，CI 困难
- 单一故障域

**结论：不推荐单容器方案。**

### 3.2 多容器方案

**优点：**
- 每个工具使用官方推荐环境，无版本冲突
- 可独立更新各容器
- GPU 仅分配给需要它的容器
- 许可证边界清晰（LightDock GPL-3.0 独立容器，各组件许可证可分别告知）
- 可独立扩缩
- 镜像体积可控

**缺点：**
- 需要 Docker Compose 或编排工具
- 共享工作目录需要 volume 挂载
- 容器间依赖需在 compose 层处理（wait-for、health check）

**结论：强烈推荐多容器方案。**

## 4. 推荐架构

```
                    ┌──────────────────────────┐
                    │   labmate-orchestrator   │
                    │   Python 3.11-slim       │
                    │   CPU only               │
                    │   MIT                    │
                    │   Port: 8501 (Streamlit) │
                    └──────────┬───────────────┘
                               │ subprocess / CLI
                               │ 共享 volume: /workspace
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐  ┌─────▼──────┐  ┌──────▼──────────┐
    │ colabfold-     │  │ lightdock- │  │ rfantibody-     │
    │ worker         │  │ worker     │  │ worker          │
    │ (仅 Live Local │  │ (必需)     │  │ (仅 labmate      │
    │  主流程需要)    │  │            │  │  design CLI)    │
    │                │  │            │  │                 │
    │ Python 3.10    │  │ Python 3.x │  │ Python 3.10     │
    │ JAX + CUDA 12  │  │ CPU only   │  │ PyTorch+CUDA 11 │
    │ GPU: 必须      │  │ GPL-3.0    │  │ GPU: 必须       │
    │ MIT            │  │            │  │ MIT             │
    └────────────────┘  └────────────┘  └─────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
    ┌─────────────────────────────────────────────────┐
    │            共享工作目录 /workspace               │
    │  /workspace/inputs/      输入文件                 │
    │  /workspace/structures/  ColabFold 输出           │
    │  /workspace/docking/     LightDock 输出           │
    │  /workspace/analysis/    分析输出                 │
    │  /workspace/ranking/     排名输出                 │
    │  /workspace/report.html  最终报告                 │
    └─────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────┐
    │             只读挂载（host → 容器）                │
    │  /models/colabfold/     ColabFold 权重            │
    │  /models/rfantibody/     RFdiffusion + ProteinMPNN│
    │  （数据库如 UniRef 仅在 MSA 模式需要；当前不需要）  │
    └─────────────────────────────────────────────────┘
```

### 4.1 各容器职责

| 容器 | 触发方式 | 需要 GPU | CUDA | 关键挂载 |
|---|---|---|---|---|
| **labmate-orchestrator** | 用户 CLI 或 Streamlit | 否 | — | 工作目录 r/w，源码 r/o |
| **colabfold-worker** | orchestrator 调用 `docker exec` 或独立 CLI | 是 | 12.1+ | 工作目录 r/w，权重 r/o |
| **lightdock-worker** | orchestrator 调用 `docker exec` 或独立 CLI | 否 | — | 工作目录 r/w |
| **rfantibody-worker** | orchestrator 调用 `docker exec`（仅 `labmate design`） | 是 | 11.8 | 工作目录 r/w，权重 r/o，RFantibody 脚本 r/o |

### 4.2 建议的 docker-compose 结构

```yaml
# docker-compose.live-local.yml（草案，不实现）
services:
  orchestrator:
    build: docker/live/orchestrator
    ports: ["8501:8501"]
    volumes:
      - workspace:/workspace
      - ./app.py:/app/app.py:ro
    depends_on:
      colabfold-worker:
        condition: service_healthy
      lightdock-worker:
        condition: service_healthy

  colabfold-worker:
    image: colabfold/colabfold:1.6.2-cu12  # 或社区镜像
    volumes:
      - workspace:/workspace
      - /host/models/colabfold:/models:ro
    deploy:
      resources:
        reservations:
          devices: [driver: nvidia, count: 1, capabilities: [gpu]]
    # 始终运行，等待 orchestrator 调用

  lightdock-worker:
    build: docker/live/lightdock
    volumes:
      - workspace:/workspace

  # 可选：仅 labmate design CLI 需要
  rfantibody-worker:
    build: docker/live/rfantibody
    volumes:
      - workspace:/workspace
      - /host/models/rfantibody/weights:/weights:ro
      - /host/rfantibody/scripts:/scripts:ro
    deploy:
      resources:
        reservations:
          devices: [driver: nvidia, count: 1, capabilities: [gpu]]
    profiles: ["design"]  # 仅在需要时启动

volumes:
  workspace:
```

### 4.3 通信模式

由于 orchestrator 使用 `subprocess.run` 调用外部可执行文件，需要在容器内可直接访问目标可执行文件。两种方案：

**方案 A：容器内 CLI 调用（推荐初期方案）**
- Orchestrator 通过 `docker exec` 在工作容器中执行命令
- 优点：无需修改 Labmate 源码，外部工具保持隔离
- 缺点：orchestrator 需要 Docker socket 访问

**方案 B：HTTP/gRPC worker 模式（长期方案）**
- 每个工具容器暴露轻量 HTTP API
- Orchestrator 通过 HTTP 提交作业、轮询状态
- 优点：更干净的抽象，适合扩展到 Live Remote
- 缺点：需要为每个工具编写 API wrapper，工作量较大

**初期实现建议：方案 A**，与现有 `subprocess.run` 模式最接近，改动最小。

## 5. GPU Passthrough 前置条件

### 5.1 Host 要求

| 要求 | 说明 |
|---|---|
| NVIDIA 驱动 | ≥525.60.13（CUDA 12 兼容）；建议最新稳定版 |
| NVIDIA Container Toolkit | `nvidia-container-toolkit` 已安装并配置 Docker runtime |
| CUDA 版本 | host 驱动需同时兼容 CUDA 11.8（RFantibody）和 CUDA 12.1+（ColabFold） |
| GPU 显存 | ≥16 GB 推荐（ColabFold 单次预测约 5.5-6 GB，含 overhead） |

### 5.2 验证命令

```bash
# 验证 GPU 可见
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi

# 验证 CUDA 11.8 兼容
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

### 5.3 Windows/WSL2 特别说明

当前 Live Local 验证在 WSL2 Ubuntu 26.04 上完成。WSL2 下 Docker GPU passthrough 需要：
- Windows 11 21H2+
- WSL2 kernel 5.10.16.3+
- NVIDIA Windows 驱动 ≥510.06（支持 WSL2 GPU）
- Docker Desktop with WSL2 backend 或在 WSL2 内安装原生 Docker

## 6. 模型权重和数据库挂载策略

### 6.1 ColabFold

| 资源 | 大小 | 挂载方式 | 获取方式 |
|---|---|---|---|
| `alphafold2_multimer_v3` 权重 ×5 | ~10 GB | **只读 volume** `/models/colabfold/params` | 用户从 AlphaFold 官方下载，不随镜像分发 |
| MMseqs2/UniRef 数据库 | 80-180 GB | **不需要**（`single_sequence` 模式） | — |

### 6.2 RFantibody

| 资源 | 大小 | 挂载方式 | 获取方式 |
|---|---|---|---|
| `RFdiffusion_Ab.pt` | ~1.7 GB | **只读 volume** `/models/rfantibody/weights` | 用户运行 `download_weights.sh`，不随镜像分发 |
| `ProteinMPNN_v48_noise_0.2.pt` | ~2 GB | **只读 volume** `/models/rfantibody/weights` | 同上 |
| RFantibody 脚本 (`scripts/`) | ~几十 MB | **只读 volume** `/scripts` 或构建进镜像 | 用户 clone RFantibody repo |
| `example_inputs/h-NbBCII10.pdb` | ~几十 KB | 同上 | 含于 RFantibody repo |

### 6.3 策略总结

- **绝不**在 Docker 镜像中嵌入模型权重、数据库、密钥或用户序列。
- 用户必须在 host 上预先下载并验证权重文件。
- 挂载前进行 SHA-256 校验（Labmate 已有此能力）。
- 模型路径通过环境变量或 job 配置传入，不硬编码于 Dockerfile。

## 7. 许可证与再分发风险

| 组件 | 许可证 | 可构建进镜像？ | 风险 |
|---|---|---|---|
| Antibody Labmate | MIT | 是 | 无 |
| RFantibody 源码 | MIT | 是（源码可） | 权重不能分发 |
| RFantibody 权重 | 需用户审核条款 | **否** | 必须用户自行下载 |
| ProteinMPNN 源码 | MIT | 是 | 权重不能分发 |
| ColabFold 源码 | MIT | 是 | AlphaFold 权重/数据条款需单独审核 |
| AlphaFold 权重 | CC BY-NC 4.0 / AlphaFold 条款 | **否** | 必须用户自行下载；非商业限制可能存在 |
| **LightDock** | **GPL-3.0** | 可构建但需保留许可证、来源和适用源代码义务 | LightDock 保持为独立安装和独立进程，通过命令行、退出码和普通文件产物与 Labmate 通信。独立容器主要用于依赖隔离、版本固定和许可证告知清晰度。容器边界本身不自动决定两个程序是否构成单一作品。本文不是法律意见；如公开分发整套镜像或紧密集成，应进一步审查许可证义务。 |
| LightDock 依赖（NumPy, SciPy 等） | BSD/MIT | 是 | 无 |

**关键建议：**
1. LightDock 作为独立容器或独立安装，通过命令行接口和文件产物与 Labmate 通信。独立容器主要服务于依赖隔离和版本固定。
2. 分发时必须保留 LightDock 的 GPL-3.0 许可证文本、版权声明和适用的源代码义务。
3. 所有模型权重和数据库通过 host volume 挂载，不进入镜像层。
4. 在文档中明确告知用户需自行获取并审核权重/数据库许可。
5. 现有 Replay-only Docker（MIT）不受影响，继续维持 MIT 分发。

## 8. 最小 Smoke Test 路线

基于已验证的 [LIVE_LOCAL_VALIDATION.md](../LIVE_LOCAL_VALIDATION.md) Smoke 参数复现：

### 8.1 输入

```
candidates=1, steps=20, swarms=4, glowworms=50, cores=2, top_poses=3
scoring=fastdfire, score_direction=higher_is_better
```

### 8.2 步骤

1. 将合成 smoke 输入（CC0 1-candidate FASTA + region CSV + antigen PDB）放入共享工作目录
2. 启动 ColabFold worker 容器（GPU），运行预测
3. 验证输出 PDB 链映射和 pLDDT
4. 启动 LightDock worker 容器（CPU），运行 docking
5. 验证 GSO 行号 → pose 映射
6. 由 orchestrator 运行 S07-S10 分析、排名、报告
7. 验证 manifest 中所有 artifact 哈希
8. 运行隐私审计（无绝对路径/token 泄露）

### 8.3 预期验证记录

应复制 [LIVE_LOCAL_VALIDATION.md](../LIVE_LOCAL_VALIDATION.md) 中的独立输出检查模式：逐残基 pLDDT 一致、GSO 行号精确、pose 链合约完整、manifest 哈希一致。

## 9. 实施阶段划分

### Phase D0：环境与许可证审计（本阶段）
- ✅ 调查各工具 Python/CUDA/依赖版本
- ✅ 确认依赖冲突
- ✅ 确认许可证风险
- ✅ 产出本可行性文档
- ⬜ 确认目标 host 环境（Linux 服务器 / WSL2 / Cloud GPU）

### Phase D1：Labmate + LightDock CPU 容器
- 编写 `docker/live/lightdock/Dockerfile`（基于 Python 3.x-slim，pip install lightdock==0.9.4）
- 验证 LightDock 0.9.4 在容器内可正常运行 setup → run → generate
- 验证 orchestrator 可通过 volume 共享工作目录调用 LightDock
- 成本：无 GPU，轻量，快速迭代

### Phase D2：RFantibody GPU 容器（可选）
- 评估是否直接复用 RFantibody 官方 Dockerfile（`nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04`）
- 或基于官方镜像构建 worker wrapper
- 在容器内运行单次 VHH 设计 smoke（1 candidate）
- 验证输出候选 PDB 的序列线程和固定 backbone 校验
- 成本：需要 GPU，镜像 ~10-15 GB

### Phase D3：ColabFold GPU 容器
- 评估社区镜像（`jysgro/colabfold` ~16.2 GB）或基于 LocalColabFold 安装脚本构建
- 或评估上游 ColabFold 官方 Docker 镜像
- 验证 `single_sequence` + `alphafold2_multimer_v3` + 预装权重路径
- 验证输出 PDB 链映射和 pLDDT 与已验证记录一致
- 成本：需要 GPU（≥16 GB 显存推荐），镜像 ~16-20 GB

### Phase D4：Docker Compose 端到端 Smoke
- 编写 `docker-compose.live-local.yml`
- 编排 orchestrator + colabfold-worker + lightdock-worker
- 运行完整 1-candidate smoke，验证端到端输出
- 对比 Docker 输出与 [LIVE_LOCAL_VALIDATION.md](../LIVE_LOCAL_VALIDATION.md) 记录的输出哈希
- 成本：需要 GPU，完整运行约 5-15 分钟

### Phase D5：第三方机器复现
- 让另一台机器（不同 host）按文档复现 D4 smoke
- 验证：不同 host 上，相同输入 → 相同输出哈希（允许 ColabFold 浮点差异时放宽）
- 记录复现环境细节
- 成本：需要额外硬件

## 10. 仍未解决的问题

| 问题 | 影响 | 建议 |
|---|---|---|
| **ColabFold 社区镜像可靠性** | D3 | 优先评估上游 ColabFold 官方 Docker 镜像；若不可用则审计社区镜像 Dockerfile |
| **DGL CUDA 11.8 wheel 可用性** | D2 | RFantibody 官方 Dockerfile 已处理；若独立构建需验证 DGL wheel 源 |
| **跨容器 subprocess 调用方式** | D1-D4 | 初期用 `docker exec`；长期考虑 HTTP wrapper |
| **ColabFold 非确定性** | D5 | AlphaFold 推理含浮点非确定性（JAX XLA）；可接受微小数值差异 |
| **LightDock GPL-3.0 分发义务** | D1 | 容器内 pip install 官方包，不修改源码；独立容器便于许可证告知清晰；如公开分发整套镜像或紧密集成，应进一步审查许可证义务 |
| **WSL2 vs 原生 Linux GPU 性能** | D4-D5 | WSL2 已验证可运行；原生 Linux 预期性能更好但未测试 |
| **RFantibody RF2 阶段** | D2+ | 官方流程包含 RF2 筛选，但 Labmate 未集成；Phase D2 仅覆盖 RFdiffusion + ProteinMPNN |
| **多候选批量运行资源** | D4-D5 | 当前 smoke 仅 1 candidate；N candidate 需要 N 次 ColabFold 调用，资源线性增长 |
| **Apptainer/Singularity HPC 替代** | D2 | RFantibody 官方提供 Apptainer `.sif` 构建方案（~8 GB）；可作为 HPC 部署备选 |

## 附录 A：调查方法

- 查阅 [labmate/live_local.py](../labmate/live_local.py) 确认真实调用链
- 查阅 [labmate/workers/rfantibody_worker.py](../labmate/workers/rfantibody_worker.py) 确认 RFantibody 依赖
- 查阅 [labmate/design/rfantibody.py](../labmate/design/rfantibody.py) 确认外部 interpreter 调用方式
- 查阅 [labmate/backends/colabfold.py](../labmate/backends/colabfold.py) 确认 ColabFold wrapper 参数
- 查阅 [LIVE_LOCAL_VALIDATION.md](../LIVE_LOCAL_VALIDATION.md) 确认已验证工具版本
- 搜索 RFantibody 官方 README / DeepWiki 确认官方 Docker 方案和依赖
- 搜索 LocalColabFold 文档确认版本要求和社区 Docker 镜像
- 搜索 LightDock GitHub/PyPI 确认版本和依赖

## 附录 B：关键版本对照

> 以下为 Antibody Labmate 当前拟采用或已验证的固定版本，随上游工具更新可能变化。
> 实施时必须以锁定的镜像 tag + digest 为准。

| 工具 | Antibody Labmate 使用/验证版本 | 官方最新 | 备注 |
|---|---|---|---|
| Antibody Labmate | 0.3.0 | — | orchestrator 当前使用 Python 3.11 |
| ColabFold | 1.6.2 (alphafold-colabfold 2.3.18) | 1.6.2 | 当前验证使用 single_sequence + multimer_v3；Python/CUDA 要求随版本变化 |
| LightDock | 0.9.4 | 0.9.4 | GPL-3.0，独立安装 |
| RFantibody | 1.0.0 (bridge) | 1.0.0 | 仅 VHH 模式；RFdiffusion + ProteinMPNN；官方要求 CUDA 11.8+ |
| RF2 | **未集成** | 含于 RFantibody 官方 | Labmate 未调用 |
| IgFold | 0.4.0 (prediction-backend smoke) | 0.4.0 | JHU Academic License；当前验证使用 Python 3.10 worker |
| IgCraft | `audited_not_integrated` | 0.0.1 (commit `4a053de`) | 接口不兼容（要求完整 PDB） |
