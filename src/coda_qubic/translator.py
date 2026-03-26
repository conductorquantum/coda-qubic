"""Translate NativeGateIR programs into QubiC's high-level gate representation."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, ClassVar

from coda_node.server.ir import GateOp, NativeGateIR

from coda_qubic.device import QubiCDeviceSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranslatedQubiCCircuit:
    program: list[dict[str, Any]]
    measurement_hardware_order: list[str]


class QubiCCircuitTranslator:
    """Lower NativeGateIR into a QubiC gate-level program."""

    _SUPPORTED_TARGETS: ClassVar[set[str]] = {
        "cz",
        "cnot",
    }

    def __init__(self, device: QubiCDeviceSpec) -> None:
        self._device = device

    def translate(self, ir: NativeGateIR) -> TranslatedQubiCCircuit:
        if ir.target not in self._SUPPORTED_TARGETS:
            raise ValueError(
                f"QubiC translator only supports cz and cnot IR, got {ir.target}"
            )
        if ir.num_qubits > self._device.num_qubits:
            raise ValueError(
                "IR requests "
                f"{ir.num_qubits} qubits but QubiC device exposes only "
                f"{self._device.num_qubits}"
            )
        self._validate_ir_indices(ir)

        program: list[dict[str, Any]] = []
        for gate_op in ir.gates:
            program.extend(self._translate_gate(gate_op, target=ir.target))

        measurement_hardware_order = [
            self._device.hardware_qubit(qubit) for qubit in ir.measurements
        ]
        for hardware_qubit in measurement_hardware_order:
            program.append({"name": "read", "qubit": [hardware_qubit]})

        return TranslatedQubiCCircuit(
            program=program,
            measurement_hardware_order=measurement_hardware_order,
        )

    def _validate_ir_indices(self, ir: NativeGateIR) -> None:
        referenced_qubits = set(ir.measurements)
        for gate_op in ir.gates:
            referenced_qubits.update(gate_op.qubits)

        for qubit in sorted(referenced_qubits):
            if qubit < 0:
                raise ValueError(
                    f"IR references invalid negative logical qubit {qubit}"
                )
            if qubit >= ir.num_qubits:
                raise ValueError(
                    f"IR references logical qubit {qubit} outside declared width {ir.num_qubits}"
                )
            if qubit >= self._device.num_qubits:
                raise ValueError(
                    f"IR references logical qubit {qubit} but QubiC device exposes only "
                    f"{self._device.num_qubits} qubits"
                )

    def _translate_gate(self, gate_op: GateOp, *, target: str) -> list[dict[str, Any]]:
        gate_name = gate_op.gate.value
        hardware_qubits = [
            self._device.hardware_qubit(qubit) for qubit in gate_op.qubits
        ]

        if target == "cnot":
            if gate_name == "x90":
                return [{"name": "X90", "qubit": hardware_qubits}]
            if gate_name == "y_minus_90":
                return [{"name": "Y-90", "qubit": hardware_qubits}]
            if gate_name == "virtual_z":
                return [
                    {
                        "name": "virtual_z",
                        "phase": gate_op.params[0],
                        "qubit": hardware_qubits,
                    }
                ]
            if gate_name == "cnot":
                return self._translate_directed_cnot(
                    gate_op.qubits[0], gate_op.qubits[1]
                )
            if gate_name == "id":
                return [
                    {
                        "name": "delay",
                        "t": gate_op.params[0] / 1e9,
                        "qubit": hardware_qubits,
                    }
                ]

        if gate_name == "rx":
            return _decompose_u(
                hardware_qubits, gate_op.params[0], -math.pi / 2, math.pi / 2
            )
        if gate_name == "ry":
            return _decompose_u(hardware_qubits, gate_op.params[0], 0.0, 0.0)
        if gate_name == "rz":
            return [
                {
                    "name": "virtual_z",
                    "phase": gate_op.params[0],
                    "qubit": hardware_qubits,
                }
            ]
        if gate_name == "id":
            return [
                {
                    "name": "delay",
                    "t": gate_op.params[0] / 1e9,
                    "qubit": hardware_qubits,
                }
            ]
        if gate_name == "cz":
            return self._translate_cz(gate_op.qubits[0], gate_op.qubits[1])
        raise ValueError(f"QubiC translator does not support gate {gate_name}")

    def _translate_cz(self, q0: int, q1: int) -> list[dict[str, Any]]:
        edge = self._device.calibrated_cnot_for_pair(q0, q1)
        if edge is None:
            raise ValueError(
                f"QubiC device has no calibrated 2Q edge for logical pair {(q0, q1)}"
            )

        target = edge.target_hardware
        return [
            *_decompose_h([target]),
            {"name": "CNOT", "qubit": [edge.control_hardware, edge.target_hardware]},
            *_decompose_h([target]),
        ]

    def _translate_directed_cnot(
        self, control: int, target: int
    ) -> list[dict[str, Any]]:
        edge = self._device.directed_cnot(control, target)
        if edge is not None:
            return [
                {"name": "CNOT", "qubit": [edge.control_hardware, edge.target_hardware]}
            ]

        # Fallback: reverse direction via (H⊗H)·CNOT(b→a)·(H⊗H).
        # The cloud compiler should already route and orient CX gates
        # for the device topology; hitting this path means the compiled
        # IR contains a CX direction the compiler did not resolve.
        reverse_edge = self._device.directed_cnot(target, control)
        if reverse_edge is not None:
            logger.warning(
                "CNOT(%d, %d) has no native edge; falling back to "
                "H-sandwich reversal via CNOT(%d, %d). The cloud compiler "
                "should handle this — check that device connectivity is "
                "being sent in heartbeats.",
                control,
                target,
                target,
                control,
            )
            ctrl_hw = self._device.hardware_qubit(control)
            tgt_hw = self._device.hardware_qubit(target)
            return [
                *_decompose_h([ctrl_hw]),
                *_decompose_h([tgt_hw]),
                {
                    "name": "CNOT",
                    "qubit": [
                        reverse_edge.control_hardware,
                        reverse_edge.target_hardware,
                    ],
                },
                *_decompose_h([ctrl_hw]),
                *_decompose_h([tgt_hw]),
            ]

        raise ValueError(
            "QubiC device has no calibrated CNOT edge for logical pair "
            f"{(control, target)}"
        )


def _phase_instr(hw_qubits: list[str], phase: float) -> dict[str, Any]:
    return {"name": "virtual_z", "phase": phase, "qubit": hw_qubits}


def _x90_instr(hw_qubits: list[str]) -> dict[str, Any]:
    return {"name": "X90", "qubit": hw_qubits}


def _decompose_h(hw_qubits: list[str]) -> list[dict[str, Any]]:
    return [
        {"name": "Y-90", "qubit": hw_qubits},
        _phase_instr(hw_qubits, math.pi),
    ]


def _decompose_u(
    hw_qubits: list[str], theta: float, phi: float, lam: float
) -> list[dict[str, Any]]:
    if (
        math.isclose(theta, math.pi / 2, abs_tol=1e-12)
        and math.isclose(phi, -math.pi / 2, abs_tol=1e-12)
        and math.isclose(lam, math.pi / 2, abs_tol=1e-12)
    ):
        return [_x90_instr(hw_qubits)]

    if (
        math.isclose(theta, -math.pi / 2, abs_tol=1e-12)
        and math.isclose(phi, 0.0, abs_tol=1e-12)
        and math.isclose(lam, 0.0, abs_tol=1e-12)
    ):
        return [{"name": "Y-90", "qubit": hw_qubits}]

    instr = [
        _phase_instr(hw_qubits, phi),
        _x90_instr(hw_qubits),
        _phase_instr(hw_qubits, math.pi - theta),
        _x90_instr(hw_qubits),
        _phase_instr(hw_qubits, lam - math.pi),
    ]
    instr.reverse()
    return instr
