# Phase D1 — LightDock CPU Worker Container

> 状态：已实现 · 未经科学验证

## 范围

Phase D1 **仅验证 LightDock 容器边界**——即 Labmate orchestrator 能否通过
固定命令和共享 volume 调用独立的 LightDock CPU 容器并获得正确产物。

**D1 不包括：**
- ColabFold GPU worker（Phase D3）
- RFantibody worker（Phase D2，可选）
- 完整的 Dockerized Live Local（需 D4 end-to-end smoke）
- 科学验证（不是 binding/affinity/free-energy/experimental 验证）
- 公共镜像分发许可证审查

## 设计原则

| 原则 | 实现 |
|---|---|
| 独立进程通信 | 仅通过 CLI 参数、退出码和普通文件产物 |
| 无 Docker socket 暴露 | Orchestrator 使用 `docker compose run --rm`，不挂载 socket |
| 参数列表传递 | 所有命令使用 list 形式，不拼接 shell 字符串 |
| 白名单子命令 | entrypoint 仅允许 version/setup/run/generate |
| Fail closed | 非零退出码 → LabmateError |
| 日志清洗 | 宿主机绝对路径和 token 模式在捕获日志中已脱敏 |

## 文件

| 文件 | 用途 |
|---|---|
| `docker/live/lightdock/Dockerfile` | Python 3.11-slim + LightDock 0.9.4 + 安全加固 |
| `docker/live/lightdock/entrypoint.sh` | 白名单子命令分发器 |
| `docker/live/lightdock/THIRD_PARTY_NOTICES_LightDock.md` | GPL-3.0 许可告知 |
| `docker-compose.live-local.yml` | 独立 Compose 文件，仅 lightdock service |
| `labmate/backends/lightdock_container.py` | Python adapter：`LightDockContainerBackend` |
| `tests/test_lightdock_container.py` | 单元测试 + 集成 smoke（需要 Docker） |

## 构建

```bash
docker compose -f docker-compose.live-local.yml build lightdock
```

## Smoke 测试

```bash
# 1. 版本检查
docker compose -f docker-compose.live-local.yml run --rm lightdock version

# 2. 创建测试输入
mkdir -p runs/docker-live/inputs runs/docker-live/outputs
cp test_receptor.pdb runs/docker-live/inputs/receptor_A.pdb
cp test_ligand.pdb runs/docker-live/inputs/antibody_HL.pdb

# 3. Setup
docker compose -f docker-compose.live-local.yml run --rm lightdock \
  setup receptor_A.pdb antibody_HL.pdb -s 2 -g 10 --noxt --noh --now

# 4. Run
docker compose -f docker-compose.live-local.yml run --rm lightdock \
  run 10 -c 2

# 5. Generate
# （先选择 top GSO 行写入 selected.gso）
docker compose -f docker-compose.live-local.yml run --rm lightdock \
  generate receptor_A.pdb antibody_HL.pdb selected.gso 3

# 6. 验证产物
ls runs/docker-live/outputs/lightdock_*.pdb
```

## GPL 容器边界

LightDock 以 **GPL-3.0** 许可分发。本容器含未修改的 pip 安装版本。

- 容器边界不是法律豁免；独立容器主要服务于依赖隔离和许可证告知清晰度。
- 容器边界本身不自动决定 Labmate 与 LightDock 是否构成单一作品。
- 如公开分发本镜像，必须遵守 GPL-3.0 的源代码提供义务。
- 本文不是法律意见。

## 尚未覆盖

- ColabFold GPU worker（Phase D3）
- 完整端到端 Docker Live Local smoke（Phase D4）
- 第三方机器复现（Phase D5）
- Docker 镜像在 Registry 上的分发和签名
- Apptainer/Singularity HPC 替代方案
- 跨平台（ARM64）构建
