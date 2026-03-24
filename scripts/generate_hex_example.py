#!/usr/bin/env python3
"""Generate a simple 20-qubit sparse-grid example for coda-qubic.

The logical qubits are arranged in a 4x5 row-major grid with a few missing
horizontal couplers so the topology still reads as a grid while staying simple:

    Q0 --- Q1 --- Q2     Q3 --- Q4
    |      |      |      |      |
    Q5 --- Q6     Q7 --- Q8     Q9
    |      |      |      |      |
   Q10 -- Q11 -- Q12    Q13    Q14
    |      |      |      |      |
   Q15 -- Q16    Q17    Q18 -- Q19

24 edges total.
"""

import json
import math
import random
from pathlib import Path

NUM_QUBITS = 20

EDGES: list[tuple[int, int]] = [
    (0, 1),
    (1, 2),
    (3, 4),
    (5, 6),
    (7, 8),
    (10, 11),
    (11, 12),
    (15, 16),
    (18, 19),
    (0, 5),
    (1, 6),
    (2, 7),
    (3, 8),
    (4, 9),
    (5, 10),
    (6, 11),
    (7, 12),
    (8, 13),
    (9, 14),
    (10, 15),
    (11, 16),
    (12, 17),
    (13, 18),
    (14, 19),
]

random.seed(42)


def _qubit_freq(qid: int) -> float:
    """Spread drive frequencies across 4.4-5.9 GHz."""
    return 4.4e9 + (qid / (NUM_QUBITS - 1)) * 1.5e9 + random.uniform(-20e6, 20e6)


def _readout_freq(qid: int) -> float:
    """Spread readout frequencies across 6.5-7.1 GHz."""
    return 6.5e9 + (qid / (NUM_QUBITS - 1)) * 0.6e9 + random.uniform(-10e6, 10e6)


def _ef_freq(drive_freq: float) -> float:
    return drive_freq - random.uniform(250e6, 320e6)


def _x90_amp() -> float:
    return round(random.uniform(0.10, 0.55), 6)


def _x90_twidth() -> float:
    return random.choice([2.4e-8, 3.2e-8, 6.4e-8])


def _read_amp() -> float:
    return round(random.uniform(0.014, 0.025), 6)


def _rdlo_phase() -> float:
    return 0.0


def _cr_twidth() -> float:
    return random.choice([2.4e-7, 3.0e-7, 3.5e-7, 4.0e-7])


def _cr_amp() -> float:
    return round(random.uniform(0.15, 0.90), 6)


def _target_pulse_amp() -> float:
    return round(random.uniform(0.10, 0.70), 6)


def build_qubitcfg() -> dict:
    qubits: dict[str, dict] = {}
    gates: dict[str, list] = {}

    drive_freqs: dict[int, float] = {}
    read_freqs: dict[int, float] = {}

    for qid in range(NUM_QUBITS):
        label = f"Q{qid}"
        df = _qubit_freq(qid)
        rf = _readout_freq(qid)
        ef = _ef_freq(df)
        drive_freqs[qid] = df
        read_freqs[qid] = rf

        qubits[label] = {
            "freq": df,
            "readfreq": rf,
            "freq_ef": ef,
        }

        twidth = _x90_twidth()
        amp = _x90_amp()

        gates[f"{label}X90"] = [
            {
                "freq": f"{label}.freq",
                "phase": 0.0,
                "dest": f"{label}.qdrv",
                "twidth": twidth,
                "t0": 0.0,
                "amp": amp,
                "env": [
                    {"env_func": "cos_edge_square", "paradict": {"ramp_fraction": 0.25}}
                ],
            }
        ]

        gates[f"{label}X90_ef"] = [
            {
                "freq": f"{label}.freq_ef",
                "phase": 0.0,
                "dest": f"{label}.qdrv",
                "twidth": twidth,
                "t0": 0.0,
                "amp": round(random.uniform(0.10, 0.75), 6),
                "env": [
                    {"env_func": "cos_edge_square", "paradict": {"ramp_fraction": 0.25}}
                ],
            }
        ]

        gates[f"{label}rabi"] = [
            {
                "freq": f"{label}.freq",
                "phase": 0.0,
                "dest": f"{label}.qdrv",
                "twidth": 1e-6,
                "t0": 0.0,
                "amp": amp,
                "env": [
                    {"env_func": "cos_edge_square", "paradict": {"ramp_fraction": 0.25}}
                ],
            }
        ]

        gates[f"{label}rabi_ef"] = [
            {
                "freq": f"{label}.freq_ef",
                "phase": 0.0,
                "dest": f"{label}.qdrv",
                "twidth": 1e-6,
                "t0": 0.0,
                "amp": round(random.uniform(0.10, 0.75), 6),
                "env": [
                    {"env_func": "cos_edge_square", "paradict": {"ramp_fraction": 0.25}}
                ],
            }
        ]

        ramp = 0.25
        read_twidth = 2e-6
        read_amp = _read_amp()
        rdlo_phase = _rdlo_phase()

        gates[f"{label}read"] = [
            {
                "freq": f"{label}.readfreq",
                "phase": 0.0,
                "dest": f"{label}.rdrv",
                "twidth": read_twidth,
                "t0": 0.0,
                "amp": read_amp,
                "env": [
                    {
                        "env_func": "cos_edge_square",
                        "paradict": {"ramp_fraction": ramp, "twidth": read_twidth},
                    }
                ],
            },
            {
                "freq": f"{label}.readfreq",
                "phase": rdlo_phase,
                "dest": f"{label}.rdlo",
                "twidth": read_twidth,
                "t0": 6e-7,
                "amp": 1.0,
                "env": [
                    {
                        "env_func": "square",
                        "paradict": {
                            "phase": 0.0,
                            "amplitude": 1.0,
                            "twidth": read_twidth,
                        },
                    }
                ],
            },
        ]

        gates[f"{label}Z90"] = [
            {"gate": "virtualz", "freq": f"{label}.freq", "phase": "numpy.pi/2.0"}
        ]

        gates[f"{label}Y-90"] = [
            {"gate": "virtualz", "freq": f"{label}.freq", "phase": "-numpy.pi/2.0"},
            {"gate": f"{label}X90"},
            {"gate": "virtualz", "freq": f"{label}.freq", "phase": "numpy.pi/2.0"},
        ]

    for a, b in EDGES:
        control, target = max(a, b), min(a, b)
        ctrl_label = f"Q{control}"
        tgt_label = f"Q{target}"
        cr_name = f"{ctrl_label}{tgt_label}CR"
        cnot_name = f"{ctrl_label}{tgt_label}CNOT"

        cr_tw = _cr_twidth()
        cr_a = _cr_amp()
        tgt_a = _target_pulse_amp()
        tgt_tw = random.choice([3.2e-8, 6.4e-8])

        gates[cr_name] = [
            {
                "freq": f"{tgt_label}.freq",
                "phase": 0.0,
                "dest": f"{ctrl_label}.qdrv",
                "twidth": cr_tw,
                "t0": 0.0,
                "amp": cr_a,
                "env": [
                    {
                        "env_func": "cos_edge_square",
                        "paradict": {"ramp_fraction": 0.25, "ramp_length": 3.2e-8},
                    }
                ],
            }
        ]

        vz_target_phase = round(random.uniform(-math.pi, math.pi), 6)
        vz_control_phase = round(random.uniform(-math.pi, math.pi), 6)

        gates[cnot_name] = [
            {"gate": "virtualz", "freq": f"{tgt_label}.freq", "phase": vz_target_phase},
            {"gate": cr_name},
            {
                "gate": "virtualz",
                "freq": f"{tgt_label}.freq",
                "phase": -vz_target_phase,
            },
            {
                "gate": "virtualz",
                "freq": f"{ctrl_label}.freq",
                "phase": vz_control_phase,
            },
            {
                "freq": f"{tgt_label}.freq",
                "phase": 0,
                "dest": f"{tgt_label}.qdrv",
                "twidth": tgt_tw,
                "t0": cr_tw,
                "amp": tgt_a,
                "env": [
                    {"env_func": "cos_edge_square", "paradict": {"ramp_fraction": 0.25}}
                ],
            },
        ]

    qubits["vna"] = {"freq": None, "readfreq": 0}
    qubits["alignment"] = {"freq": None, "readfreq": 6200000000.0}

    return {"Qubits": qubits, "Gates": gates}


def build_channel_config() -> dict:
    config: dict[str, object] = {"fpga_clk_freq": 500000000.0}

    for qid in range(NUM_QUBITS):
        label = f"Q{qid}"
        core = qid

        config[f"{label}.qdrv"] = {
            "core_ind": core,
            "elem_ind": 0,
            "core_name": "qubit",
            "env_mem_name": f"qubit_qdrv_env{qid}",
            "freq_mem_name": f"qubit_qdrv_freq{qid}",
            "elem_params": {"interp_ratio": 4, "samples_per_clk": 16},
            "elem_type": "rf",
        }

        config[f"{label}.rdrv"] = {
            "core_ind": core,
            "elem_ind": 1,
            "core_name": "qubit",
            "env_mem_name": f"qubit_rdrv_env{qid}",
            "freq_mem_name": f"qubit_rdrv_freq{qid}",
            "elem_params": {"interp_ratio": 16, "samples_per_clk": 16},
            "elem_type": "rf",
        }

        config[f"{label}.rdlo"] = {
            "core_ind": core,
            "elem_ind": 2,
            "core_name": "qubit",
            "env_mem_name": f"qubit_rdlo_env{qid}",
            "freq_mem_name": f"qubit_rdlo_freq{qid}",
            "elem_params": {"interp_ratio": 4, "samples_per_clk": 4},
            "acc_mem_name": f"qubit_accbuf{qid}",
            "elem_type": "rf_mix",
        }

    return config


def build_gmm_classifier() -> dict:
    classifier: dict[str, object] = {
        "_comment": "Minimal GMM classifier placeholder for testing",
        "_note": "Replace with actual GMM classifier parameters from calibration",
        "qubits": {},
    }
    qubits_dict: dict[str, object] = {}

    for qid in range(NUM_QUBITS):
        qubits_dict[f"Q{qid}"] = {
            "means": [[0.0, 0.0], [1.0, 0.0]],
            "covariances": [[[0.1, 0.0], [0.0, 0.1]], [[0.1, 0.0], [0.0, 0.1]]],
            "weights": [0.5, 0.5],
        }

    classifier["qubits"] = qubits_dict
    return classifier


def main() -> None:
    qubitcfg = build_qubitcfg()
    channel_config = build_channel_config()
    gmm = build_gmm_classifier()
    root = Path(__file__).resolve().parents[1]
    outputs = {
        root / "examples" / "qubitcfg.json": qubitcfg,
        root / "examples" / "channel_config.json": channel_config,
        root / "examples" / "gmm_classifier.json": gmm,
        root / "site" / "qubitcfg.json": qubitcfg,
        root / "site" / "channel_config.json": channel_config,
        root / "site" / "gmm_classifier.json": gmm,
    }

    for path, payload in outputs.items():
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(payload, indent=4) + "\n")
        print(f"Wrote {path}")

    print(
        f"\nGenerated {NUM_QUBITS}-qubit sparse-grid example with {len(EDGES)} edges:"
    )
    for a, b in EDGES:
        ctrl, tgt = max(a, b), min(a, b)
        print(f"  Q{ctrl} -> Q{tgt}  (CNOT)")


if __name__ == "__main__":
    main()
