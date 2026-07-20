# Antibody Labmate — CDR-to-Docking Workflow

> **REPLAY ONLY · FIXED HASH-VERIFIED DEMO · NOT LIVE COMPUTE**

🌐 **Live Replay Demo:** [Open Antibody Labmate](https://antibodylabmate-jxifsgmgfipzdh7nrx3wdz.streamlit.app/)

这是按照《Antibody Labmate 最终执行路线 v1.1》实现的 Phase 1 Replay MVP。它接受六条明确分开的 IMGT CDR 和抗原 PDB，验证输入后，只对与 `fixtures/demo_001` **精确匹配**的合成数据执行 Replay。运行时会重新完成 PDB 解析、候选/结构/docking 固定输出解析、界面几何分析、候选启发式排名、HTML 报告和 ZIP 打包。

本版本不会安装、调用或模拟 IgCraft、ColabFold、LightDock、ElliDock、HDOCK、PyMOL 或远程 worker。Live Local 与 Live Remote 均为 `unavailable`。

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

测试覆盖 CDR 标准化和非法字符、PDB 大小/链/MODEL/altloc、状态机、固定 fixture 与输入 SHA-256、LightDock Live gate、界面接触与 clash、归一化边界、HTML/manifest/ZIP，以及三类篡改拒绝路径。

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
- Live Local：`unavailable`。
- Live Remote：`unavailable`。
- ElliDockProvider/HDOCKProvider：Phase 1 不创建虚假 skeleton，也不出现在可运行选择框。
- 普通 DiffDock：不属于蛋白–蛋白 docking 后端。

## 科学、隐私与合规声明

本工作流生成的是计算候选与计算优先级排名。结构预测置信度、对接分数及几何接触分析不能证明真实结合、亲和力、特异性、安全性或治疗效果。任何实验、公开传播或商业使用均应由使用者完成必要的序列权利确认、风险评估和实验验证。

报告只写相对 artifact 路径，不写 token、API key、环境变量或本机绝对路径。Replay 不联网，不向外部服务发送序列或结构。

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

本 Phase 1 实现由 Codex 根据用户提供的 v1.1 路线和明确产品决策协助创建，包括数据模型、Replay 状态机、校验器、分析/排名、报告、UI 与测试。项目负责人仍需对科学措辞、fixture 权利、比赛展示、提交时段内实际贡献和最终发布负责；Git、README、Devpost 与视频中的贡献描述应与事实一致。

## 当前未验证部分

- IgCraft CDR-only carrier/inpainting；
- ColabFold VH:VL complex、链映射与实际输出 schema；
- LightDock 安装、命令、性能、真实 score/pose materialization 与 GPL 组合分发；
- ElliDock GPU/Linux；
- HDOCK 书面许可 gate；
- PyMOL 渲染；
- Live Local、fully offline、Live Remote、鉴权、隔离、取消、超时和数据清理。

上述内容属于后续 Phase 0 Spike / Phase 2–3，不是本版本的可用能力。
