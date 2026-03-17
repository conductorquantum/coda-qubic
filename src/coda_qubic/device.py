"""Derive a conservative self-service device spec from a QubiC qubitcfg file."""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

_HARDWARE_QUBIT_RE = re.compile(r"^Q(\d+)$")
_DIRECTED_CR_RE = re.compile(r"^Q(\d+)Q(\d+)CR$")


def _seconds_to_ns(value: float | int | None) -> int:
    if value is None:
        return 0
    return round(float(value) * 1e9)


def _extract_hardware_qubit_id(label: str) -> int:
    match = _HARDWARE_QUBIT_RE.fullmatch(label)
    if match is None:
        raise ValueError(f"Invalid hardware qubit label: {label}")
    return int(match.group(1))


def _extract_named_frequency(reference: Any) -> str | None:
    return reference if isinstance(reference, str) else None


@dataclass(frozen=True)
class QubiCSingleQubitCalibration:
    logical_qubit: int
    hardware_qubit: str
    drive_frequency_hz: float
    drive_amplitude: float
    x90_duration_ns: int
    readout_frequency_hz: float
    readout_amplitude: float
    readout_duration_ns: int
    readout_phase_rad: float


@dataclass(frozen=True)
class DirectedCNOTCalibration:
    control_logical: int
    target_logical: int
    control_hardware: str
    target_hardware: str
    cr_duration_ns: int
    cr_amplitude: float
    target_pulse_duration_ns: int
    target_pulse_amplitude: float


class _SingleQubitCalibrationData(TypedDict):
    drive_frequency_hz: float
    drive_amplitude: float
    x90_duration_ns: int
    readout_frequency_hz: float
    readout_amplitude: float
    readout_duration_ns: int
    readout_phase_rad: float


class _DirectedEdgeData(TypedDict):
    cr_duration_ns: int
    cr_amplitude: float
    target_pulse_duration_ns: int
    target_pulse_amplitude: float


@dataclass(frozen=True)
class QubiCDeviceSpec:
    logical_to_hardware: tuple[str, ...]
    qubits: dict[int, QubiCSingleQubitCalibration]
    directed_cnot_edges: dict[tuple[int, int], DirectedCNOTCalibration]

    @property
    def num_qubits(self) -> int:
        return len(self.logical_to_hardware)

    @property
    def hardware_to_logical(self) -> dict[str, int]:
        return {
            hardware: logical
            for logical, hardware in enumerate(self.logical_to_hardware)
        }

    @property
    def logical_edges(self) -> list[tuple[int, int]]:
        pairs = {
            (min(control, target), max(control, target))
            for control, target in self.directed_cnot_edges
        }
        return sorted(pairs)

    def hardware_qubit(self, logical_qubit: int) -> str:
        return self.logical_to_hardware[logical_qubit]

    def calibrated_cnot_for_pair(
        self, q0: int, q1: int
    ) -> DirectedCNOTCalibration | None:
        if (q0, q1) in self.directed_cnot_edges:
            return self.directed_cnot_edges[(q0, q1)]
        if (q1, q0) in self.directed_cnot_edges:
            return self.directed_cnot_edges[(q1, q0)]
        return None

    def directed_cnot(
        self, control: int, target: int
    ) -> DirectedCNOTCalibration | None:
        return self.directed_cnot_edges.get((control, target))

    def export_calibration_snapshot(self) -> dict[str, object]:
        return {
            "num_qubits": self.num_qubits,
            "logical_to_hardware": list(self.logical_to_hardware),
            "qubits": [
                {
                    "logical_qubit": logical,
                    "hardware_qubit": cal.hardware_qubit,
                    "drive_frequency_hz": cal.drive_frequency_hz,
                    "drive_amplitude": cal.drive_amplitude,
                    "x90_duration_ns": cal.x90_duration_ns,
                    "readout_frequency_hz": cal.readout_frequency_hz,
                    "readout_amplitude": cal.readout_amplitude,
                    "readout_duration_ns": cal.readout_duration_ns,
                }
                for logical, cal in sorted(self.qubits.items())
            ],
            "directed_cnot_edges": [
                {
                    "control_logical": edge.control_logical,
                    "target_logical": edge.target_logical,
                    "control_hardware": edge.control_hardware,
                    "target_hardware": edge.target_hardware,
                    "cr_duration_ns": edge.cr_duration_ns,
                    "cr_amplitude": edge.cr_amplitude,
                    "target_pulse_duration_ns": edge.target_pulse_duration_ns,
                    "target_pulse_amplitude": edge.target_pulse_amplitude,
                }
                for _, edge in sorted(self.directed_cnot_edges.items())
            ],
            "missing_characterization": [
                "t1",
                "t2",
                "single_qubit_fidelity",
                "two_qubit_fidelity",
            ],
        }

    @classmethod
    def from_qubitcfg(cls, path: str | Path) -> QubiCDeviceSpec:
        config_path = Path(path)
        raw = json.loads(config_path.read_text())
        qubits_section = raw["Qubits"]
        gates_section = raw["Gates"]

        single_qubit = _extract_single_qubit_calibrations(qubits_section, gates_section)
        directed_edges_hw = _extract_directed_edges(gates_section, single_qubit)
        if not directed_edges_hw:
            raise ValueError(f"No usable two-qubit calibrations found in {config_path}")

        chosen_component = _largest_connected_component(directed_edges_hw)
        hardware_order = tuple(f"Q{qid}" for qid in sorted(chosen_component))
        hardware_to_logical = {
            label: logical for logical, label in enumerate(hardware_order)
        }

        qubits = {
            hardware_to_logical[hardware]: QubiCSingleQubitCalibration(
                logical_qubit=hardware_to_logical[hardware],
                hardware_qubit=hardware,
                drive_frequency_hz=cal["drive_frequency_hz"],
                drive_amplitude=cal["drive_amplitude"],
                x90_duration_ns=cal["x90_duration_ns"],
                readout_frequency_hz=cal["readout_frequency_hz"],
                readout_amplitude=cal["readout_amplitude"],
                readout_duration_ns=cal["readout_duration_ns"],
                readout_phase_rad=cal["readout_phase_rad"],
            )
            for hardware, cal in single_qubit.items()
            if hardware in hardware_to_logical
        }

        directed_cnot_edges = {}
        for (control_hw, target_hw), edge in directed_edges_hw.items():
            if (
                control_hw not in hardware_to_logical
                or target_hw not in hardware_to_logical
            ):
                continue
            control_logical = hardware_to_logical[control_hw]
            target_logical = hardware_to_logical[target_hw]
            directed_cnot_edges[(control_logical, target_logical)] = (
                DirectedCNOTCalibration(
                    control_logical=control_logical,
                    target_logical=target_logical,
                    control_hardware=control_hw,
                    target_hardware=target_hw,
                    cr_duration_ns=edge["cr_duration_ns"],
                    cr_amplitude=edge["cr_amplitude"],
                    target_pulse_duration_ns=edge["target_pulse_duration_ns"],
                    target_pulse_amplitude=edge["target_pulse_amplitude"],
                )
            )

        return cls(
            logical_to_hardware=hardware_order,
            qubits=qubits,
            directed_cnot_edges=directed_cnot_edges,
        )


def _extract_single_qubit_calibrations(
    qubits_section: dict[str, Any], gates_section: dict[str, Any]
) -> dict[str, _SingleQubitCalibrationData]:
    result: dict[str, _SingleQubitCalibrationData] = {}
    for hardware, qubit_cfg in qubits_section.items():
        if _HARDWARE_QUBIT_RE.fullmatch(hardware) is None:
            continue

        x90_gate = gates_section.get(f"{hardware}X90")
        read_gate = gates_section.get(f"{hardware}read")
        if not x90_gate or not read_gate:
            continue

        drive_pulse = x90_gate[0]
        readout_drive = next(
            (pulse for pulse in read_gate if pulse.get("dest") == f"{hardware}.rdrv"),
            None,
        )
        readout_lo = next(
            (pulse for pulse in read_gate if pulse.get("dest") == f"{hardware}.rdlo"),
            None,
        )
        if readout_drive is None or readout_lo is None:
            continue

        drive_frequency_hz = qubit_cfg.get("freq")
        readout_frequency_hz = qubit_cfg.get("readfreq")
        if drive_frequency_hz is None or readout_frequency_hz is None:
            continue

        result[hardware] = {
            "drive_frequency_hz": float(drive_frequency_hz),
            "drive_amplitude": float(drive_pulse["amp"]),
            "x90_duration_ns": _seconds_to_ns(drive_pulse["twidth"]),
            "readout_frequency_hz": float(readout_frequency_hz),
            "readout_amplitude": float(readout_drive["amp"]),
            "readout_duration_ns": _seconds_to_ns(readout_drive["twidth"]),
            "readout_phase_rad": float(readout_lo.get("phase", 0.0)),
        }

    return result


def _extract_directed_edges(
    gates_section: dict[str, Any],
    single_qubit: dict[str, _SingleQubitCalibrationData],
) -> dict[tuple[str, str], _DirectedEdgeData]:
    result: dict[tuple[str, str], _DirectedEdgeData] = {}
    for gate_name, cr_gate in gates_section.items():
        match = _DIRECTED_CR_RE.fullmatch(gate_name)
        if match is None:
            continue

        control_hw = f"Q{match.group(1)}"
        target_hw = f"Q{match.group(2)}"
        if control_hw not in single_qubit or target_hw not in single_qubit:
            continue

        cnot_gate = gates_section.get(f"{control_hw}{target_hw}CNOT")
        if not cnot_gate:
            continue

        cr_pulse = next(
            (pulse for pulse in cr_gate if pulse.get("dest") == f"{control_hw}.qdrv"),
            None,
        )
        target_pulse = next(
            (pulse for pulse in cnot_gate if pulse.get("dest") == f"{target_hw}.qdrv"),
            None,
        )
        if cr_pulse is None or target_pulse is None:
            continue

        cr_duration_ns = _seconds_to_ns(cr_pulse.get("twidth"))
        target_pulse_duration_ns = _seconds_to_ns(target_pulse.get("twidth"))
        cr_amplitude = float(cr_pulse.get("amp", 0.0) or 0.0)
        target_pulse_amplitude = float(target_pulse.get("amp", 0.0) or 0.0)

        # Placeholder entries exist in the sample file. Only keep gates with a
        # real CR pulse and a non-degenerate target pulse in the composite CNOT.
        if cr_duration_ns <= 0 or target_pulse_duration_ns <= 0:
            continue
        if abs(cr_amplitude) <= 0.0 or abs(target_pulse_amplitude) <= 0.0:
            continue

        result[(control_hw, target_hw)] = {
            "cr_duration_ns": cr_duration_ns,
            "cr_amplitude": cr_amplitude,
            "target_pulse_duration_ns": target_pulse_duration_ns,
            "target_pulse_amplitude": target_pulse_amplitude,
        }

    return result


def _largest_connected_component(
    directed_edges_hw: dict[tuple[str, str], _DirectedEdgeData],
) -> set[int]:
    adjacency: dict[int, set[int]] = defaultdict(set)
    for control_hw, target_hw in directed_edges_hw:
        control_id = _extract_hardware_qubit_id(control_hw)
        target_id = _extract_hardware_qubit_id(target_hw)
        adjacency[control_id].add(target_id)
        adjacency[target_id].add(control_id)

    components: list[list[int]] = []
    seen: set[int] = set()
    for node in sorted(adjacency):
        if node in seen:
            continue
        queue = deque([node])
        component: list[int] = []
        seen.add(node)
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in sorted(adjacency[current]):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
        components.append(sorted(component))

    if not components:
        raise ValueError("No connected components found for directed QubiC edges")

    components.sort(key=lambda component: (-len(component), component))
    return set(components[0])
