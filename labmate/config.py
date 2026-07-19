"""Configuration constants for the bounded Replay MVP."""

from dataclasses import dataclass


@dataclass(frozen=True)
class InputLimits:
    """Safety limits, not biological or IgCraft checkpoint limits."""

    max_cdr_length: int = 80
    max_pdb_bytes: int = 2 * 1024 * 1024
    max_pdb_atoms: int = 50_000
    max_pdb_chains: int = 16


@dataclass(frozen=True)
class InterfaceConfig:
    contact_cutoff_angstrom: float = 4.5
    polar_contact_cutoff_angstrom: float = 3.5
    ionic_contact_cutoff_angstrom: float = 4.0
    severe_clash_cutoff_angstrom: float = 2.0
    analyze_top_poses: int = 2


DEFAULT_INPUT_LIMITS = InputLimits()
DEFAULT_INTERFACE_CONFIG = InterfaceConfig()

SCIENTIFIC_LIMITATION = (
    "本工作流生成的是计算候选与计算优先级排名。结构预测置信度、对接分数及几何接触分析"
    "不能证明真实结合、亲和力、特异性、安全性或治疗效果。任何实验、公开传播或商业使用均应"
    "由使用者完成必要的序列权利确认、风险评估和实验验证。"
)

