"""Shared fixtures for coda-qubic tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _x90_gate(qubit: str, *, amp: float) -> list[dict[str, object]]:
    return [
        {
            "freq": f"{qubit}.freq",
            "phase": 0.0,
            "dest": f"{qubit}.qdrv",
            "twidth": 24e-9,
            "t0": 0.0,
            "amp": amp,
            "env": [
                {
                    "env_func": "cos_edge_square",
                    "paradict": {"ramp_fraction": 0.25},
                }
            ],
        }
    ]


def _read_gate(qubit: str) -> list[dict[str, object]]:
    return [
        {
            "freq": f"{qubit}.readfreq",
            "phase": 0.0,
            "dest": f"{qubit}.rdrv",
            "twidth": 2e-6,
            "t0": 0.0,
            "amp": 0.02,
            "env": [
                {
                    "env_func": "cos_edge_square",
                    "paradict": {"ramp_fraction": 0.25},
                }
            ],
        },
        {
            "freq": f"{qubit}.readfreq",
            "phase": 0.0,
            "dest": f"{qubit}.rdlo",
            "twidth": 2e-6,
            "t0": 0.6e-6,
            "amp": 1.0,
            "env": [
                {
                    "env_func": "square",
                    "paradict": {"phase": 0.0, "amplitude": 1.0},
                }
            ],
        },
    ]


def _cr_gate(
    control: str, target: str, *, twidth_s: float, amp: float
) -> list[dict[str, object]]:
    return [
        {
            "dest": f"{control}.qdrv",
            "freq": f"{target}.freq",
            "phase": 0.0,
            "twidth": twidth_s,
            "t0": 0.0,
            "amp": amp,
            "env": [
                {
                    "env_func": "cos_edge_square",
                    "paradict": {"ramp_fraction": 0.25},
                }
            ],
        }
    ]


def _cnot_gate(
    control: str,
    target: str,
    *,
    target_twidth_s: float,
    target_amp: float,
    cr_gate_name: str,
    t0_s: float,
) -> list[dict[str, object]]:
    return [
        {"gate": "virtualz", "freq": f"{target}.freq", "phase": -0.2},
        {"gate": cr_gate_name},
        {"gate": "virtualz", "freq": f"{target}.freq", "phase": 0.2},
        {"gate": "virtualz", "freq": f"{control}.freq", "phase": 0.3},
        {
            "freq": f"{target}.freq",
            "phase": 0.0,
            "dest": f"{target}.qdrv",
            "twidth": target_twidth_s,
            "t0": t0_s,
            "amp": target_amp,
            "env": [
                {
                    "env_func": "cos_edge_square",
                    "paradict": {"ramp_fraction": 0.25},
                }
            ],
        },
    ]


def _sample_qubic_qubitcfg() -> dict[str, object]:
    qubits: dict[str, dict[str, float]] = {}
    gates: dict[str, list[dict[str, object]]] = {}

    for qid in range(1, 7):
        qubit = f"Q{qid}"
        qubits[qubit] = {
            "freq": 4.5e9 + qid * 1e8,
            "readfreq": 6.5e9 + qid * 1e8,
        }
        gates[f"{qubit}X90"] = _x90_gate(qubit, amp=0.1 + qid * 0.01)
        gates[f"{qubit}read"] = _read_gate(qubit)

    gates["Q2Q1CR"] = _cr_gate("Q2", "Q1", twidth_s=300e-9, amp=0.35)
    gates["Q2Q1CNOT"] = _cnot_gate(
        "Q2",
        "Q1",
        target_twidth_s=32e-9,
        target_amp=0.22,
        cr_gate_name="Q2Q1CR",
        t0_s=300e-9,
    )

    gates["Q3Q2CR"] = _cr_gate("Q3", "Q2", twidth_s=400e-9, amp=0.31)
    gates["Q3Q2CNOT"] = _cnot_gate(
        "Q3",
        "Q2",
        target_twidth_s=64e-9,
        target_amp=0.19,
        cr_gate_name="Q3Q2CR",
        t0_s=400e-9,
    )

    gates["Q6Q5CR"] = _cr_gate("Q6", "Q5", twidth_s=280e-9, amp=0.29)
    gates["Q6Q5CNOT"] = _cnot_gate(
        "Q6",
        "Q5",
        target_twidth_s=32e-9,
        target_amp=0.21,
        cr_gate_name="Q6Q5CR",
        t0_s=280e-9,
    )

    gates["Q5Q4CR"] = _cr_gate("Q5", "Q4", twidth_s=0.0, amp=0.25)
    gates["Q5Q4CNOT"] = _cnot_gate(
        "Q5",
        "Q4",
        target_twidth_s=32e-9,
        target_amp=0.2,
        cr_gate_name="Q5Q4CR",
        t0_s=0.0,
    )

    gates["Q4Q3CR"] = _cr_gate("Q4", "Q3", twidth_s=0.0, amp=0.24)
    gates["Q4Q3CNOT"] = _cnot_gate(
        "Q4",
        "Q3",
        target_twidth_s=32e-9,
        target_amp=0.18,
        cr_gate_name="Q4Q3CR",
        t0_s=0.0,
    )

    return {"Qubits": qubits, "Gates": gates}


def _sample_qubic_channel_config() -> dict[str, object]:
    return {
        "Q1.rdlo": {"acc_mem_name": "Q1.rdlo"},
        "Q2.rdlo": {"acc_mem_name": "Q2.rdlo"},
        "Q3.rdlo": {"acc_mem_name": "Q3.rdlo"},
    }


@pytest.fixture(scope="session")
def qubic_example_qubitcfg_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("qubic-fixtures") / "qubitcfg.json"
    path.write_text(json.dumps(_sample_qubic_qubitcfg()))
    return path


@pytest.fixture(scope="session")
def qubic_example_channel_config_path(
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    path = tmp_path_factory.mktemp("qubic-fixtures") / "channel_config.json"
    path.write_text(json.dumps(_sample_qubic_channel_config()))
    return path
