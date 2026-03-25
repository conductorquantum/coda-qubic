"""Simulator integration tests for common quantum circuits.

These tests compile representative circuits (GHZ-style entanglement, H⊗³,
approximate QFT, Grover) in the ``superconducting_cnot`` native gate set and
execute them through QubiC's pulse-level simulator via ``QubiCJobRunner``.

The current LBNL pulse simulator + example calibration can yield readout
statistics that do not match ideal gate-model expectations; assertions here
focus on **end-to-end integration** (no crashes, shot accounting, non-trivial
readout). For stricter physics checks against a different backend, run those
in a separate harness.

All tests are skipped when the QubiC vendor stack is not installed.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
from pathlib import Path
from typing import Any

import pytest
from self_service.server.executor import ExecutionResult
from self_service.server.ir import GateOp, IRMetadata, NativeGateIR

from coda_qubic.config import QubiCConfig
from coda_qubic.executor_factory import build_executor
from coda_qubic.support import load_qubic_dependencies

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"

_deps: Any = None
with contextlib.suppress(Exception):
    _deps = load_qubic_dependencies()

pytestmark = pytest.mark.skipif(
    _deps is None, reason="QubiC simulator dependencies unavailable"
)


def _metadata() -> IRMetadata:
    return IRMetadata(
        source_hash="sim-circuit-test", compiled_at="2026-03-19T00:00:00Z"
    )


@pytest.fixture(scope="module")
def sim_executor() -> Any:
    config = QubiCConfig.from_yaml(str(EXAMPLES_DIR / "device_sim.yaml"))
    return build_executor(config, dependencies=_deps)


def _run(executor: Any, ir: NativeGateIR, shots: int = 1000) -> ExecutionResult:
    return asyncio.run(executor.run(ir, shots))


def _device_num_qubits(executor: Any) -> int:
    return executor.device.num_qubits


def _assert_integration_result(result: ExecutionResult, shots: int) -> None:
    assert result.shots_completed == shots
    assert sum(result.counts.values()) == shots
    # Three measured qubits → eight computational outcomes in the normalized map.
    assert len(result.counts) == 8


# -- gate decomposition helpers ----------------------------------------
# The simulator fixture loads the 20-qubit example device, but these circuits
# intentionally exercise only logical qubits 0, 1, and 2.
# Available directed CNOTs on that local subgraph: (1, 0) and (2, 1).


def _h(qubit: int) -> list[GateOp]:
    """Hadamard: Y(-90) followed by Z(pi)."""
    return [
        GateOp(gate="y_minus_90", qubits=[qubit], params=[]),
        GateOp(gate="virtual_z", qubits=[qubit], params=[math.pi]),
    ]


def _x(qubit: int) -> list[GateOp]:
    """X gate via two X90 pulses (= Rx(pi), equivalent to X up to global phase)."""
    return [
        GateOp(gate="x90", qubits=[qubit], params=[]),
        GateOp(gate="x90", qubits=[qubit], params=[]),
    ]


def _rz(qubit: int, theta: float) -> list[GateOp]:
    return [GateOp(gate="virtual_z", qubits=[qubit], params=[theta])]


def _cnot(control: int, target: int) -> list[GateOp]:
    """Direct CNOT — caller must ensure the directed edge exists."""
    return [GateOp(gate="cnot", qubits=[control, target], params=[])]


def _cz_01() -> list[GateOp]:
    """CZ on (q0, q1) = H(q0) · CNOT(1,0) · H(q0)."""
    return [*_h(0), *_cnot(1, 0), *_h(0)]


def _crz(theta: float, control: int, target: int) -> list[GateOp]:
    """Controlled-Rz(theta) decomposed into virtual_z + CNOT."""
    return [
        *_rz(target, theta / 2),
        *_cnot(control, target),
        *_rz(target, -theta / 2),
        *_cnot(control, target),
    ]


# =====================================================================
# 1. GHZ-style entangling sequence (connectivity: CNOT 2→1, 1→0)
# =====================================================================


class TestGHZState:
    def test_ghz_circuit_executes_with_valid_counts(self, sim_executor: Any) -> None:
        shots = 1000
        gates = [*_h(2), *_cnot(2, 1), *_cnot(1, 0)]
        ir = NativeGateIR(
            num_qubits=_device_num_qubits(sim_executor),
            target="superconducting_cnot",
            gates=gates,
            measurements=[0, 1, 2],
            metadata=_metadata(),
        )
        result = _run(sim_executor, ir, shots=shots)
        _assert_integration_result(result, shots)
        assert max(result.counts.values()) < shots, (
            "expect some spread across readout outcomes from pulse sim + GMM"
        )


# =====================================================================
# 2. Hadamard layer on all qubits
# =====================================================================


class TestUniformSuperposition:
    def test_hadamard_layer_executes_with_valid_counts(self, sim_executor: Any) -> None:
        shots = 2000
        gates = [*_h(0), *_h(1), *_h(2)]
        ir = NativeGateIR(
            num_qubits=_device_num_qubits(sim_executor),
            target="superconducting_cnot",
            gates=gates,
            measurements=[0, 1, 2],
            metadata=_metadata(),
        )
        result = _run(sim_executor, ir, shots=shots)
        _assert_integration_result(result, shots)


# =====================================================================
# 3. Approximate 3-qubit QFT (nearest-neighbour only)
# =====================================================================


class TestApproximateQFT:
    def test_aqft_circuit_executes_with_valid_counts(self, sim_executor: Any) -> None:
        shots = 2000
        state_prep = [*_x(0), *_x(2)]

        qft_body = [
            *_h(0),
            *_crz(math.pi / 2, control=1, target=0),
            *_h(1),
            *_crz(math.pi / 2, control=2, target=1),
            *_h(2),
        ]

        ir = NativeGateIR(
            num_qubits=_device_num_qubits(sim_executor),
            target="superconducting_cnot",
            gates=[*state_prep, *qft_body],
            measurements=[0, 1, 2],
            metadata=_metadata(),
        )
        result = _run(sim_executor, ir, shots=shots)
        _assert_integration_result(result, shots)


# =====================================================================
# 4. Grover-style iteration on q0,q1 (spectator q2)
# =====================================================================


class TestGroverTwoQubit:
    def test_grover_style_circuit_executes_with_valid_counts(
        self, sim_executor: Any
    ) -> None:
        shots = 1000
        oracle = _cz_01()

        diffusion = [
            *_h(0),
            *_h(1),
            *_x(0),
            *_x(1),
            *_cz_01(),
            *_x(0),
            *_x(1),
            *_h(0),
            *_h(1),
        ]

        circuit = [
            *_h(0),
            *_h(1),
            *oracle,
            *diffusion,
        ]

        ir = NativeGateIR(
            num_qubits=_device_num_qubits(sim_executor),
            target="superconducting_cnot",
            gates=circuit,
            measurements=[0, 1, 2],
            metadata=_metadata(),
        )
        result = _run(sim_executor, ir, shots=shots)
        _assert_integration_result(result, shots)


class TestSimulatorCircuitDifferentiation:
    """Sanity check that translation produces distinct programs."""

    def test_representative_circuits_translate_to_different_depths(
        self, sim_executor: Any
    ) -> None:
        translator = sim_executor._translator
        ir_ghz = NativeGateIR(
            num_qubits=_device_num_qubits(sim_executor),
            target="superconducting_cnot",
            gates=[*_h(2), *_cnot(2, 1), *_cnot(1, 0)],
            measurements=[0, 1, 2],
            metadata=_metadata(),
        )
        oracle = _cz_01()
        diffusion = [
            *_h(0),
            *_h(1),
            *_x(0),
            *_x(1),
            *_cz_01(),
            *_x(0),
            *_x(1),
            *_h(0),
            *_h(1),
        ]
        ir_grover = NativeGateIR(
            num_qubits=_device_num_qubits(sim_executor),
            target="superconducting_cnot",
            gates=[*_h(0), *_h(1), *oracle, *diffusion],
            measurements=[0, 1, 2],
            metadata=_metadata(),
        )
        len_ghz = len(translator.translate(ir_ghz).program)
        len_grover = len(translator.translate(ir_grover).program)
        assert len_ghz != len_grover, (
            f"expected different program lengths, got {len_ghz} for both"
        )
