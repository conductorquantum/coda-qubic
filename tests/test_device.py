from __future__ import annotations

import json
from pathlib import Path

import pytest

from coda_qubic.device import QubiCDeviceSpec


class TestQubiCDeviceSpec:
    def test_selects_largest_connected_subgraph(
        self, qubic_example_qubitcfg_path: Path
    ):
        spec = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)

        assert spec.num_qubits == 3
        assert spec.logical_to_hardware == ("Q1", "Q2", "Q3")
        assert spec.logical_edges == [(0, 1), (1, 2)]

    def test_preserves_directed_cnot_orientation(
        self, qubic_example_qubitcfg_path: Path
    ):
        spec = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)

        assert sorted(spec.directed_cnot_edges) == [(1, 0), (2, 1)]
        edge_10 = spec.directed_cnot_edges[(1, 0)]
        edge_21 = spec.directed_cnot_edges[(2, 1)]

        assert edge_10.control_hardware == "Q2"
        assert edge_10.target_hardware == "Q1"
        assert edge_10.cr_duration_ns == 300
        assert edge_10.target_pulse_duration_ns == 32

        assert edge_21.control_hardware == "Q3"
        assert edge_21.target_hardware == "Q2"
        assert edge_21.cr_duration_ns == 400
        assert edge_21.target_pulse_duration_ns == 64

    def test_exports_future_calibration_snapshot(
        self, qubic_example_qubitcfg_path: Path
    ):
        spec = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)

        snapshot = spec.export_calibration_snapshot()

        assert snapshot["num_qubits"] == 3
        assert snapshot["logical_to_hardware"] == ["Q1", "Q2", "Q3"]
        assert snapshot["missing_characterization"] == [
            "t1",
            "t2",
            "single_qubit_fidelity",
            "two_qubit_fidelity",
        ]

    def test_tie_breaks_equal_components_by_lowest_hardware_labels(self, tmp_path):
        path = _write_qubitcfg(
            tmp_path,
            qubits=("Q0", "Q1", "Q4", "Q5"),
            edges=(("Q0", "Q1"), ("Q5", "Q4")),
        )

        spec = QubiCDeviceSpec.from_qubitcfg(path)

        assert spec.logical_to_hardware == ("Q0", "Q1")
        assert sorted(spec.directed_cnot_edges) == [(0, 1)]

    def test_excludes_edge_without_matching_cnot(self, tmp_path):
        path = _write_qubitcfg(
            tmp_path,
            qubits=("Q0", "Q1"),
            edges=(("Q1", "Q0"),),
            include_cnot=False,
        )

        with pytest.raises(ValueError, match="No usable two-qubit calibrations"):
            QubiCDeviceSpec.from_qubitcfg(path)

    def test_excludes_edge_with_zero_target_pulse(self, tmp_path):
        path = _write_qubitcfg(
            tmp_path,
            qubits=("Q0", "Q1"),
            edges=(("Q1", "Q0"),),
            target_pulse_amp=0.0,
        )

        with pytest.raises(ValueError, match="No usable two-qubit calibrations"):
            QubiCDeviceSpec.from_qubitcfg(path)

    def test_find_path_adjacent(self, qubic_example_qubitcfg_path: Path):
        spec = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        assert spec.find_path(0, 1) == [0, 1]
        assert spec.find_path(1, 0) == [1, 0]

    def test_find_path_through_intermediate(self, qubic_example_qubitcfg_path: Path):
        spec = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        assert spec.find_path(0, 2) == [0, 1, 2]
        assert spec.find_path(2, 0) == [2, 1, 0]

    def test_find_path_same_qubit(self, qubic_example_qubitcfg_path: Path):
        spec = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        assert spec.find_path(1, 1) == [1]

    def test_excludes_edge_when_single_qubit_calibration_missing(self, tmp_path):
        path = _write_qubitcfg(
            tmp_path,
            qubits=("Q0", "Q1"),
            edges=(("Q1", "Q0"),),
            omit_single_qubit={"Q0"},
        )

        with pytest.raises(ValueError, match="No usable two-qubit calibrations"):
            QubiCDeviceSpec.from_qubitcfg(path)


def _write_qubitcfg(
    tmp_path,
    *,
    qubits: tuple[str, ...],
    edges: tuple[tuple[str, str], ...],
    include_cnot: bool = True,
    target_pulse_amp: float = 0.22,
    omit_single_qubit: set[str] | None = None,
) -> Path:
    omit_single_qubit = omit_single_qubit or set()
    data: dict[str, object] = {"Qubits": {}, "Gates": {}}
    qubits_dict: dict[str, object] = {}
    gates_dict: dict[str, object] = {}

    for index, qubit in enumerate(qubits):
        qid = int(qubit[1:])
        qubits_dict[qubit] = {
            "freq": 4.5e9 + qid * 1e8,
            "readfreq": 6.5e9 + qid * 1e8,
        }
        if qubit in omit_single_qubit:
            continue

        gates_dict[f"{qubit}X90"] = [
            {
                "freq": f"{qubit}.freq",
                "phase": 0.0,
                "dest": f"{qubit}.qdrv",
                "twidth": 24e-9,
                "t0": 0.0,
                "amp": 0.1 + index * 0.01,
                "env": [
                    {"env_func": "cos_edge_square", "paradict": {"ramp_fraction": 0.25}}
                ],
            }
        ]
        gates_dict[f"{qubit}read"] = [
            {
                "freq": f"{qubit}.readfreq",
                "phase": 0.0,
                "dest": f"{qubit}.rdrv",
                "twidth": 2e-6,
                "t0": 0.0,
                "amp": 0.02,
                "env": [
                    {"env_func": "cos_edge_square", "paradict": {"ramp_fraction": 0.25}}
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
                    {"env_func": "square", "paradict": {"phase": 0.0, "amplitude": 1.0}}
                ],
            },
        ]

    for control, target in edges:
        gates_dict[f"{control}{target}CR"] = [
            {
                "dest": f"{control}.qdrv",
                "freq": f"{target}.freq",
                "phase": 0.0,
                "twidth": 300e-9,
                "t0": 0.0,
                "amp": 0.35,
                "env": [
                    {"env_func": "cos_edge_square", "paradict": {"ramp_fraction": 0.25}}
                ],
            }
        ]
        if include_cnot:
            gates_dict[f"{control}{target}CNOT"] = [
                {"gate": "virtualz", "freq": f"{target}.freq", "phase": -0.2},
                {"gate": f"{control}{target}CR"},
                {"gate": "virtualz", "freq": f"{target}.freq", "phase": 0.2},
                {"gate": "virtualz", "freq": f"{control}.freq", "phase": 0.3},
                {
                    "freq": f"{target}.freq",
                    "phase": 0.0,
                    "dest": f"{target}.qdrv",
                    "twidth": 32e-9,
                    "t0": 300e-9,
                    "amp": target_pulse_amp,
                    "env": [
                        {
                            "env_func": "cos_edge_square",
                            "paradict": {"ramp_fraction": 0.25},
                        }
                    ],
                },
            ]

    data["Qubits"] = qubits_dict
    data["Gates"] = gates_dict

    path = tmp_path / "synthetic_qubitcfg.json"
    path.write_text(json.dumps(data))
    return path
