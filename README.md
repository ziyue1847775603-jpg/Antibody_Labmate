# Antibody Labmate — CDR-to-Docking Workflow

> **REPLAY + VERIFIED LIVE LOCAL + IMPLEMENTED-UNVERIFIED BENCHMARK LOCAL · NO LIVE REMOTE**

本版本保留 Phase 1 Replay MVP，并新增 Phase 2a Live Local CLI。Replay 接受六条明确分开的 IMGT CDR 和抗原 PDB，验证输入后，只对与 `fixtures/demo_001` **精确匹配**的合成数据执行固定产物重放。运行时会重新完成 PDB 解析、界面几何分析、候选启发式排名、HTML 报告和 ZIP 打包。

Streamlit 页面仍只展示 Replay。CLI 另提供 `verified_live` 的 Live Local 路径：它调用用户自行安装的 ColabFold 与 LightDock；不会下载、捆绑或模拟这两个工具。该状态只覆盖 [`LIVE_LOCAL_VALIDATION.md`](LIVE_LOCAL_VALIDATION.md) 记录的本机小规模配置，不代表其他版本、参数或科学有效性。Live Remote 仍为 `unavailable`。

CLI 还提供 Phase 2b `benchmark_local`：本地抗体 PDB 与抗原 PDB 直接进入用户独立安装的 LightDock，可选用天然复合物计算 RMSD、Fnat 和界面 precision/recall/F1。它跳过 ColabFold、不接受 FASTA、不联网。当前已完成代码测试与一次真实 LightDock 0.9.4 CC0 synthetic 软件集成 smoke，但尚未完成 DB5.5 科学 benchmark，状态固定为 `implemented_unverified`；详见 [`BENCHMARK_LOCAL.md`](BENCHMARK_LOCAL.md) 和 [`BENCHMARK_LOCAL_VALIDATION.md`](BENCHMARK_LOCAL_VALIDATION.md)。

## Benchmark Local（真实 synthetic 集成已运行、科学未验证）

复制 [`examples/benchmark_local`](examples/benchmark_local)，确认输入与软件权利，填写四个显式本地 executable 路径和 score direction 后运行：

```bash
labmate run project.json --mode benchmark_local
```

成功运行生成 `poses.csv`、`interface_residues.csv`、可选 `benchmark_metrics.csv`、`case_summary.csv`、自包含 HTML、manifest、规范化输入、Top pose PDB、日志和 ZIP。报告固定标记 `BENCHMARK LOCAL · COMPUTATIONAL DOCKING BENCHMARK · NOT BINDING OR AFFINITY EVIDENCE`。

## Live Local（已验证限定配置、CLI-only）

Live Local 接受完整 VH/VL 候选 FASTA、精确的 region CSV 和一个单链抗原 PDB。它依次调用本机 ColabFold、LightDock，再执行几何界面分析、候选排名和 HTML 报告。所有外部命令输出写入 run 日志；成功完成全部校验后，报告与 manifest 标记为 `LIVE LOCAL · VERIFIED LIVE`。

开始前请单独安装并确认本机可运行 `colabfold_batch`、`lightdock3_setup.py`、`lightdock3.py`、`lgd_generate_conformations.py`。工具不会由本项目安装。配置会 fail closed：必须显式指定 MSA 模式、预装模型目录和 `alphafold2_multimer_v3`；模板使用不联系公共 MSA 服务的 `single_sequence`。复制 [`examples/live_local`](examples/live_local) 到仓库外并填写有权处理的输入后：

```bash
labmate run project.json --mode live_local --output runs
```

详细输入格式见 [`examples/live_local/README.md`](examples/live_local/README.md)。真实验证记录、工具版本、失败与修复、输出哈希及未覆盖范围见 [`LIVE_LOCAL_VALIDATION.md`](LIVE_LOCAL_VALIDATION.md)。新机器或不同工具版本仍应先用很小的 smoke 参数运行并复核日志、PDB 链映射、score-pose 对应关系和 manifest。

## 最短评委运行路径

需要 Python 3.11。在项目根目录执行：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
labmate run fixtures/demo_001/project.yaml --mode replay --fixture demo_001
streamlit run app.py
```

Windows 10/11 PowerShell（故意不激活虚拟环境，避免 PowerShell 执行策略
阻断激活脚本）：

```powershell
py -3.11 --version
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\labmate.exe run fixtures\demo_001\project.yaml --mode replay --fixture demo_001
.\.venv\Scripts\python.exe -m streamlit run app.py
```

如果 `py -3.11` 不存在，请先从 Python 官方发行版安装 64-bit Python
3.11，并勾选 Python Launcher。更完整的 Windows 与 Streamlit Community
Cloud 步骤见 [`DEPLOYMENT.md`](DEPLOYMENT.md)。

浏览器打开 Streamlit 显示的本地地址。点击 `Run verified REPLAY` 后，可以下载：

- `candidate_ranking.csv`
- `interface_residues.csv`
- 单文件离线 `report.html`
- 带阶段、版本、许可证、输入/输出哈希和警告的 `manifest.json`
- 完整运行 ZIP

## 测试

```bash
python -m pytest
```

测试覆盖 CDR 标准化和非法字符、PDB 大小/链/MODEL/altloc、Replay 状态机与 fixture 哈希、真实 ColabFold 文件配对/链映射/pLDDT、LightDock GSO 行号/分数/pose 映射、界面接触与 clash、归一化边界、隐私清洗、HTML/manifest/ZIP，以及篡改拒绝路径。

Benchmark Local 测试另覆盖 VH/VL、VHH、rights/URL/链映射拒绝、严格 PDB 结构检查、外部进程失败、score/pose 一一对应、人工可验证 RMSD/Fnat/界面指标以及 manifest 路径隐私。测试中的临时 executable 是明确的 test double，不是 LightDock，也不构成 live 验证。

Streamlit 启动烟测：

```bash
streamlit run app.py --server.headless true --server.port 8501
```

## Streamlit 部署

根目录 `requirements.txt` 仅转引不含 pytest 的
`requirements-runtime.lock`；`.streamlit/config.toml` 固定 headless、2 MiB
上传限制、CORS/XSRF 保护、关闭遥测并隐藏浏览器端错误细节。Community Cloud
部署时入口为 `app.py`，在 Advanced settings 选择 Python 3.11；不需要
`packages.txt` 或 secrets。

## Replay 的真实性边界

`demo_001` 的序列、坐标、结构质量数值、docking score 和 pose 都由 `scripts/build_demo_fixture.py` 确定性生成，专用于软件测试，采用 CC0-1.0。它不包含专利/保密 CDR、第三方二进制或第三方科学工具输出。

ReplayBackend 启动时会：

1. 校验 fixture 权利 gate；
2. 校验 manifest 中列出的每个 fixture 文件 SHA-256；
3. 规范化六条 CDR，并计算抗体输入哈希；
4. 对上传 PDB 的原始字节计算哈希；
5. 计算包含配置的输入 bundle 哈希；
6. 只有三个哈希全部与 fixture 完全相同才继续。

因此，编辑 CDR、修改 PDB 任意字节或篡改 fixture 都会被拒绝。UI 允许编辑/上传，是为了真实展示校验行为；它不会把固定结果套在自定义输入上。

## 实际执行的阶段

| 阶段 | P0 行为 | 外部科学工具 |
|---|---|---|
| S00–S01 | 建立任务、规范化 CDR、解析并清理 PDB | 不调用 |
| S02–S06 | 读取并解析哈希验证后的合成固定产物 | 不调用 |
| S07 | 由 Python 重新计算 4.5 Å 接触、距离型 polar/ionic heuristic 与 severe clash | 不依赖 PyMOL |
| S08 | 由 Python 重新完成方向对齐、run 内 min–max、子分数、综合排名和权重敏感性 | 不调用 |
| S09 | `skipped_optional`，不创建占位图 | PyMOL 不调用 |
| S10 | Jinja2 autoescape 生成单文件离线 HTML，生成 manifest 与 ZIP | 不访问网络 |

顶层 mode 和每个 `StageRecord.execution_kind` 都固定为 `replay`。S07–S10 虽然由项目代码现场执行，也不会在报告中写成 Live。

## 排名定义

```text
FinalScore = 0.35 × StructureScore
           + 0.45 × DockingScore
           + 0.20 × InterfaceScore
```

各指标先声明 `higher_is_better` 或 `lower_is_better`，只在同一 Replay run 内归一化到 0–100。`max == min` 时统一记 50；可选指标缺失时只在对应子分数组内重分配剩余权重；综合分数相同则并列。报告同时保留原始值、归一化值、权重、pose 数、clash 和权重敏感性。

这些规则是产品启发式，不是实验拟合模型。`synthetic_fixture_score` 不是 LightDock score、亲和力或结合自由能。

## PDB 解析范围

Phase 1 支持上传单个文本 `.pdb`，默认限制为 2 MiB、50,000 个 ATOM、16 条链。解析器：

- 只保留第一个 MODEL；
- 只保留用户选择链中的标准蛋白 `ATOM`；
- 删除 `HETATM` 与非标准 ATOM，并记录数量；
- altloc 选择规则为 blank 优先于 A；
- 保留 chain ID、residue number 和 insertion code；
- 输出原始到清理后 residue mapping；
- 不下载 PDB、不访问任意 URL、不补建缺失结构。

这些是 P0 基本解析能力，不替代成熟的结构准备流程。

## 目录与产物契约

```text
antibody-labmate/
├── app.py
├── labmate/
│   ├── models.py
│   ├── state.py
│   ├── workflow.py
│   ├── validators/
│   ├── backends/replay.py
│   ├── docking/lightdock.py
│   ├── analysis/
│   └── reporting/
├── fixtures/demo_001/
├── .streamlit/config.toml
├── scripts/build_demo_fixture.py
├── tests/
├── DEPLOYMENT.md
├── RELEASE_NOTES.md
├── DEMO_SCRIPT.md
├── DEVPOST_PROJECT_DESCRIPTION.md
├── pyproject.toml
├── requirements.txt
├── requirements-runtime.lock
└── requirements.lock
```

成功运行目录至少包含：

```text
RUN_ID/
├── report.html
├── job.json
├── manifest.json
├── manifest.sha256
├── candidates.fasta
├── candidate_ranking.csv
├── interface_residues.csv
├── inputs/
├── candidates/
├── structures/
├── docking/
├── analysis/
├── ranking/
├── figures/
└── logs/
```

`manifest.json` 不列出自身哈希，以避免循环定义；旁路文件 `manifest.sha256` 校验 manifest。ZIP 位于 run 目录旁，不写进 manifest，也避免自引用。

## Capability 状态

- ReplayBackend：`replay_only`，仅对 `demo_001` 的精确输入启用。
- LightDockProvider：默认 docking provider 契约，`replay_only`。只实现固定 CSV/PDB schema 解析；调用 `dock()` 会抛出明确错误。
- Live Local：`verified_live`，仅本机 CLI；验证范围为 ColabFold 1.6.2、离线 `single_sequence`、预装 multimer-v3 权重、外部 LightDock 0.9.4 和一候选小规模 smoke 参数。其他版本、MSA-backed 模式、评分函数、规模和科学有效性不在该状态范围内。
- Benchmark Local：`implemented_unverified`，本地 PDB→外部 LightDock→界面与可选 reference 指标已实现，并完成一次记录在案的真实 LightDock 0.9.4 synthetic 软件集成 smoke；尚未完成 DB5.5 科学 benchmark。
- Live Remote：`unavailable`。
- ElliDockProvider/HDOCKProvider：Phase 1 不创建虚假 skeleton，也不出现在可运行选择框。
- 普通 DiffDock：不属于蛋白–蛋白 docking 后端。

## 科学、隐私与合规声明

本工作流生成的是计算候选与计算优先级排名。结构预测置信度、对接分数及几何接触分析不能证明真实结合、亲和力、特异性、安全性或治疗效果。任何实验、公开传播或商业使用均应由使用者完成必要的序列权利确认、风险评估和实验验证。

PDB 数据许可与专利自由实施是两个不同问题；使用者负责输入数据权利、专利分析及所有外部软件授权。Schrödinger/PIPER 只能由具备许可的用户独立运行，作为外部商业对照；本仓库不调用、不捆绑其程序、脚本、License、密钥或专有输出。

报告只写相对 artifact 路径和去标识化命令名，不写 token、API key、实际环境变量、用户名或本机绝对路径。Replay 不联网。已验证的 Live Local 配置使用 `single_sequence`，不向公共 MSA 服务发送序列；应用也不下载模型。

## 重新生成合成 fixture

只在有意更新 golden fixture 时执行：

```bash
python -m scripts.build_demo_fixture
python -m pytest
```

脚本使用固定时间元数据和确定性内容，最后重建 `fixture_manifest.json` 的文件哈希。任何算法变化导致 golden 顺序或行数变化时，应由贡献者审查并明确更新 `expected/golden.json`，不能静默接受。

创建不含虚拟环境、缓存或本地 run 的干净源码 ZIP：

```bash
python -m scripts.package_project
```

发布脚本会拒绝 Git 元数据、虚拟环境、缓存、run、嵌套 ZIP、常见秘密文件、
高置信凭证模式、本机工作区/临时目录以及符号链接，并在 ZIP 内写入
`SOURCE_CHECKSUMS.sha256`。发布 ZIP 必须生成在项目目录之外。

## AI 辅助与贡献记录

本项目由 Codex 根据用户提供的路线和明确产品决策协助实现，包括 Phase 1 Replay 及 Phase 2a Live Local 的数据模型、状态机、校验器、适配器、分析/排名、报告、UI 与测试。项目负责人仍需对科学措辞、输入权利、展示和最终发布负责；Git、README、Devpost 与视频中的贡献描述应与事实一致。

## 当前未验证部分

- 应用内 IgCraft 执行与模型验证；
- ColabFold 公共或本地 MSA-backed 模式、模板模式、其他版本/模型、批量规模与性能；
- LightDock 其他版本、评分函数、大规模参数、性能与任何 GPL 组合分发；
- Benchmark Local 的 DB5.5 科学 benchmark、性能与跨版本可重复性；
- ElliDock GPU/Linux；
- HDOCK 与 Schrödinger（均未使用、未实现）；
- PyMOL 渲染；
- Live Remote、鉴权、隔离、取消、超时和数据清理；
- 任何亲和力、结合自由能、疗效、安全性或实验结论。

上述内容不是本版本的已验证能力。`verified_live` 只表示记录范围内的软件集成链路真实完成并经产物核对。
