"""Streamlit UI for the strict Replay demo; Live Local is intentionally CLI-only."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from labmate.backends.replay import ReplayBackend
from labmate.docking.registry import capability_matrix
from labmate.errors import LabmateError
from labmate.models import JobSpec, RunResult
from labmate.validators.antigen import parse_antigen_pdb
from labmate.workflow import load_project

ROOT = Path(__file__).resolve().parent
FIXTURE_ROOT = ROOT / "fixtures" / "demo_001"
PROJECT_FILE = FIXTURE_ROOT / "project.yaml"
RUNS_ROOT = ROOT / "runs"
PREDICTION_BACKEND_OPTIONS = {
    "replay": (
        "Replay (Demo)",
        "Deterministic offline demonstration",
    ),
    "colabfold": (
        "ColabFold",
        "AlphaFold2 based local prediction",
    ),
    "igfold": (
        "IgFold",
        "Local paired VH/VL prediction-only; unavailable on this Replay web host",
    ),
}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def reset_demo(demo_job: JobSpec) -> None:
    for field in ("h_cdr1", "h_cdr2", "h_cdr3", "l_cdr1", "l_cdr2", "l_cdr3"):
        st.session_state[f"cdr_{field}"] = getattr(demo_job.antibody, field)
    st.session_state.pop("run_result", None)
    st.session_state.pop("run_error", None)


st.set_page_config(page_title="Antibody Labmate — REPLAY", page_icon="🧬", layout="wide")
st.markdown(
    """
    <style>
    .replay-fixed { position:sticky; top:2.8rem; z-index:999; background:#9d1717; color:white;
      font-weight:900; letter-spacing:.12em; padding:.7rem 1rem; text-align:center; border-radius:.45rem;
      box-shadow:0 3px 12px #0004; margin-bottom:1rem; }
    .cap-card { border:1px solid #d8dee8; border-radius:.65rem; padding:.8rem; min-height:8.5rem; }
    .cap-ok { border-left:6px solid #a11212; }
    .cap-off { border-left:6px solid #6b7280; opacity:.9; }
    </style>
    <div class="replay-fixed">REPLAY · FIXED HASH-VERIFIED DEMO · NOT LIVE COMPUTE</div>
    """,
    unsafe_allow_html=True,
)

demo_job, demo_antigen_bytes = load_project(PROJECT_FILE)
if "cdr_h_cdr1" not in st.session_state:
    reset_demo(demo_job)

st.title("Antibody Labmate — CDR-to-Docking Workflow")
st.caption("网页仍是 Phase 1 Replay 演示：只重放精确匹配的合成 fixture；不会在网页中运行或模拟 IgCraft、ColabFold、LightDock 或远程 worker。六条 CDR 不能在此网页生成 framework 或完整 VH/VL；真实本地计算需要完整 VH/VL。")

st.info(
    """
    🚀 **Live Local 已开放自托管部署**

    具备本地 GPU 和所需外部工具环境的用户，可按照 GitHub 文档运行：

    **RFantibody → ProteinMPNN → ColabFold（AlphaFold2-based）→ LightDock**

    当前公开网页仍运行 Replay 演示，不在公共 Streamlit 服务执行实时计算。

    [查看 GitHub 源码与部署说明](https://github.com/ziyue1847775603-jpg/Antibody_Labmate)
    """
)

capabilities = capability_matrix()
cap_cols = st.columns(4)
with cap_cols[0]:
    st.markdown(
        '<div class="cap-card cap-ok"><strong>Replay</strong><br><code>replay_only</code><br>精确输入与 fixture 文件 SHA-256 全部匹配后可运行。</div>',
        unsafe_allow_html=True,
    )
with cap_cols[1]:
    st.markdown(
        '<div class="cap-card cap-ok"><strong>Live Local</strong><br><code>verified_live</code><br>已开放本地 GPU / GPU 服务器自托管部署；公共 Streamlit 网页仍为 Replay-only。</div>',
        unsafe_allow_html=True,
    )
with cap_cols[2]:
    st.markdown(
        '<div class="cap-card cap-off"><strong>Benchmark Local</strong><br><code>implemented_unverified</code><br>仅限本机 CLI；真实 synthetic 集成 smoke 已完成，DB5.5 科学验证未完成。</div>',
        unsafe_allow_html=True,
    )
with cap_cols[3]:
    st.markdown(
        '<div class="cap-card cap-off"><strong>Live Remote</strong><br><code>unavailable</code><br>没有 API、worker、鉴权或任务隔离。</div>',
        unsafe_allow_html=True,
    )

new_run_tab, status_tab, results_tab, settings_tab = st.tabs(["New Run", "Run Status", "Results", "Settings"])

with new_run_tab:
    left, right = st.columns([2, 1])
    with left:
        st.subheader("六条 IMGT CDR")
        if st.button("Load verified demo", type="secondary"):
            reset_demo(demo_job)
            st.rerun()
        heavy_col, light_col = st.columns(2)
        with heavy_col:
            h_cdr1 = st.text_input("H-CDR1", key="cdr_h_cdr1")
            h_cdr2 = st.text_input("H-CDR2", key="cdr_h_cdr2")
            h_cdr3 = st.text_input("H-CDR3", key="cdr_h_cdr3")
        with light_col:
            l_cdr1 = st.text_input("L-CDR1", key="cdr_l_cdr1")
            l_cdr2 = st.text_input("L-CDR2", key="cdr_l_cdr2")
            l_cdr3 = st.text_input("L-CDR3", key="cdr_l_cdr3")
        st.info("六条 CDR 仅用于固定 Replay 演示，不会生成 framework 或完整 VH/VL。可编辑字段用于演示校验失败行为；任何规范化后哈希不同的 CDR 都会被 ReplayBackend 拒绝，不会套用 demo 结果。")

    with right:
        st.subheader("抗原 PDB")
        antigen_choice = st.radio(
            "输入来源",
            ["Verified demo antigen", "Upload PDB (must byte-match demo)"],
            help="上传入口会先做大小、ATOM 坐标、链、MODEL 与 altloc 的基本解析；Replay 仍要求字节哈希精确匹配。",
        )
        uploaded = None
        if antigen_choice.startswith("Upload"):
            uploaded = st.file_uploader("Upload .pdb", type=["pdb"], accept_multiple_files=False)
        antigen_bytes = uploaded.getvalue() if uploaded is not None else demo_antigen_bytes
        try:
            preview = parse_antigen_pdb(antigen_bytes, selected_chains=demo_job.antigen.chains)
            st.success(
                f"PDB 基本解析通过：链 {', '.join(preview.chains)}；{len(preview.atoms)} atoms；"
                f"{preview.residue_count} residues；MODEL {preview.selected_model}。"
            )
            for warning in preview.warnings:
                st.warning(warning)
        except LabmateError as exc:
            st.error(str(exc))
        st.text_input("Mode", value="REPLAY", disabled=True)
        prediction_backend_name = st.selectbox(
            "Structure prediction backend",
            options=tuple(PREDICTION_BACKEND_OPTIONS),
            index=0,
            format_func=lambda name: PREDICTION_BACKEND_OPTIONS[name][0],
        )
        st.caption(PREDICTION_BACKEND_OPTIONS[prediction_backend_name][1])
        if prediction_backend_name != "replay":
            st.warning(
                "This engine is exposed by the local prediction CLI. "
                "The web workflow remains the hash-verified Replay demo."
            )
        st.text_input("DockingProvider", value="LightDockProvider · replay_only", disabled=True)
        st.number_input("Candidate count", value=4, disabled=True)
        st.number_input("Random seed", value=42, disabled=True)

    rights_confirmed = st.checkbox(
        "我确认本次加载的是项目自建 CC0 合成 demo，并理解输出不是实验结合、亲和力、疗效或安全性结论。",
        value=True,
    )
    if st.button(
        "Run verified REPLAY",
        type="primary",
        disabled=not rights_confirmed or prediction_backend_name != "replay",
    ):
        payload = demo_job.model_dump(mode="json")
        payload["antibody"].update(
            {
                "h_cdr1": h_cdr1,
                "h_cdr2": h_cdr2,
                "h_cdr3": h_cdr3,
                "l_cdr1": l_cdr1,
                "l_cdr2": l_cdr2,
                "l_cdr3": l_cdr3,
            }
        )
        payload["rights_confirmed"] = rights_confirmed
        try:
            job = JobSpec.model_validate(payload)
            backend = ReplayBackend(FIXTURE_ROOT)
            with st.spinner("REPLAY：验证输入与 fixture 哈希，并重新运行解析、界面分析、排名和报告……"):
                result = backend.submit(job, antigen_bytes, RUNS_ROOT)
            st.session_state["run_result"] = result.model_dump(mode="json")
            st.session_state.pop("run_error", None)
            st.success(f"REPLAY 完成：{result.run_id}")
        except (LabmateError, ValidationError, OSError) as exc:
            st.session_state["run_error"] = str(exc)
            st.session_state.pop("run_result", None)
            st.error(str(exc))

with status_tab:
    st.error("REPLAY 持续标识：所有阶段属于固定 fixture 重放；没有 Live 模型或 docking 执行。")
    if "run_error" in st.session_state:
        st.error(st.session_state["run_error"])
    result_payload = st.session_state.get("run_result")
    if not result_payload:
        st.info("尚未运行 verified demo。")
    else:
        result = RunResult.model_validate(result_payload)
        stage_rows = [
            {
                "stage": record.stage_id,
                "name": record.name,
                "status": record.status.value,
                "execution_kind": record.execution_kind.value,
                "provider": record.provider,
                "notes": "; ".join(record.notes),
            }
            for record in result.stages
        ]
        st.dataframe(stage_rows, use_container_width=True, hide_index=True)

with results_tab:
    st.error("REPLAY RESULTS · synthetic software-test data · not affinity or free energy")
    result_payload = st.session_state.get("run_result")
    if not result_payload:
        st.info("完成一次 verified Replay 后显示结果与下载。")
    else:
        result = RunResult.model_validate(result_payload)
        run_dir = Path(result.run_dir)
        ranking_rows = read_csv_rows(run_dir / "candidate_ranking.csv")
        interface_rows = read_csv_rows(run_dir / "interface_residues.csv")
        st.subheader("计算优先级排名")
        st.dataframe(ranking_rows, use_container_width=True, hide_index=True)
        st.subheader("界面残基表")
        st.dataframe(interface_rows, use_container_width=True, hide_index=True)

        downloads = st.columns(4)
        with downloads[0]:
            st.download_button(
                "Download ZIP",
                data=Path(result.zip_path).read_bytes(),
                file_name=Path(result.zip_path).name,
                mime="application/zip",
                use_container_width=True,
            )
        with downloads[1]:
            st.download_button(
                "report.html",
                data=Path(result.report_path).read_bytes(),
                file_name="report.html",
                mime="text/html",
                use_container_width=True,
            )
        with downloads[2]:
            st.download_button(
                "ranking.csv",
                data=(run_dir / "candidate_ranking.csv").read_bytes(),
                file_name="candidate_ranking.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with downloads[3]:
            st.download_button(
                "interface.csv",
                data=(run_dir / "interface_residues.csv").read_bytes(),
                file_name="interface_residues.csv",
                mime="text/csv",
                use_container_width=True,
            )

with settings_tab:
    st.subheader("Capability settings")
    st.json(capabilities)
    st.selectbox("Mode", ["Replay"], disabled=True)
    st.selectbox("DockingProvider contract", ["LightDockProvider (replay_only)"], disabled=True)
    st.checkbox("PyMOL", value=False, disabled=True, help="S09 固定为 skipped_optional；不创建占位图。")
    st.caption("网页只提供安全的 Replay 演示。Live Local 与 Benchmark Local 只能从本机 CLI 运行；Benchmark Local 仍为 implemented_unverified。manifest 记录去标识化命令名、真实版本和相对 artifact 路径。Remote 仍不存在。")
