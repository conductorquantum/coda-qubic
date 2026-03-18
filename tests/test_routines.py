"""Routine tests for CON-50: Berkeley QPU validation.

Tests marked with ``@pytest.mark.hardware`` require a physical QPU
connection and are skipped in CI.  Run them with::

    pytest -m hardware

Non-hardware tests verify the benchmarking module's correctness
(Clifford group properties, RB fitting, gate ordering, etc.).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from self_service.server.ir import GATE_SPECS, LEGAL_GATES, GateOp, IRMetadata, NativeGateIR

from coda_qubic.benchmarks import (
    CLIFFORD_1Q_DECOMPOSITIONS,
    CLIFFORD_1Q_MATRICES,
    bell_state_circuit,
    clifford_1q_inverse,
    cnot_average_gate_fidelity,
    cnot_truth_table_circuits,
    compose_cliffords_1q,
    fit_rb_decay,
    generate_rb_sequence_1q,
    rb_ir_circuit_1q,
)
from coda_qubic.device import QubiCDeviceSpec
from coda_qubic.translator import QubiCCircuitTranslator


def _metadata() -> IRMetadata:
    return IRMetadata(
        source_hash="sha256:routine-test", compiled_at="2026-03-17T00:00:00Z"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def device(qubic_example_qubitcfg_path: Path) -> QubiCDeviceSpec:
    return QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)


@pytest.fixture
def real_device() -> QubiCDeviceSpec:
    cfg = Path(__file__).parent.parent / "examples" / "qubitcfg.json"
    return QubiCDeviceSpec.from_qubitcfg(cfg)


@pytest.fixture
def hardware_runner() -> Any:
    """Provide a ``QubiCJobRunner`` connected to real hardware.

    Skips when hardware is unavailable.  To enable, set the
    ``CODA_QUBIC_HARDWARE`` environment variable and supply a valid
    device configuration.
    """
    import os

    if not os.environ.get("CODA_QUBIC_HARDWARE"):
        pytest.skip("Set CODA_QUBIC_HARDWARE=1 to run hardware tests")
    raise NotImplementedError(
        "Wire up a real QubiCJobRunner from environment config"
    )


# ===================================================================
# 1. Universal gate test
# ===================================================================


class TestUniversalGateSet:
    """Assert that our IR gate set is a subset of the calibrated QubiC gates."""

    def test_superconducting_cnot_gates_have_calibrations(
        self, device: QubiCDeviceSpec
    ) -> None:
        ir_gates = LEGAL_GATES["superconducting_cnot"]

        if "x90" in ir_gates:
            for q in device.qubits.values():
                assert (
                    q.x90_duration_ns > 0
                ), f"Missing X90 calibration on {q.hardware_qubit}"
                assert (
                    q.drive_amplitude > 0
                ), f"Zero X90 amplitude on {q.hardware_qubit}"

        if "cnot" in ir_gates:
            assert (
                len(device.directed_cnot_edges) > 0
            ), "No calibrated CNOT edges"
            for (ctrl, tgt), edge in device.directed_cnot_edges.items():
                assert (
                    edge.cr_duration_ns > 0
                ), f"Zero CR duration for CNOT({ctrl},{tgt})"
                assert (
                    abs(edge.cr_amplitude) > 0
                ), f"Zero CR amplitude for CNOT({ctrl},{tgt})"

        for q in device.qubits.values():
            assert (
                q.readout_duration_ns > 0
            ), f"Missing readout on {q.hardware_qubit}"
            assert (
                q.readout_amplitude > 0
            ), f"Zero readout amplitude on {q.hardware_qubit}"

    def test_superconducting_cz_decompositions_have_calibrations(
        self, device: QubiCDeviceSpec
    ) -> None:
        ir_gates = LEGAL_GATES["superconducting_cz"]

        if any(g in ir_gates for g in ("rx", "ry", "cz")):
            for q in device.qubits.values():
                assert (
                    q.x90_duration_ns > 0
                ), f"Missing X90 for ZXZXZ decomposition on {q.hardware_qubit}"

        if "cz" in ir_gates:
            assert (
                len(device.directed_cnot_edges) > 0
            ), "CZ needs CNOT edges for H-CNOT-H decomposition"

    def test_every_ir_gate_is_translatable(self, device: QubiCDeviceSpec) -> None:
        translator = QubiCCircuitTranslator(device)

        for target in ("superconducting_cz", "superconducting_cnot"):
            for gate_name in LEGAL_GATES[target]:
                spec = GATE_SPECS[gate_name]
                qubits: list[int]

                if spec["qubits"] == 2:
                    if target == "superconducting_cnot":
                        directed = list(device.directed_cnot_edges.keys())
                        if not directed:
                            pytest.skip("No directed CNOT edges")
                        qubits = list(directed[0])
                    else:
                        edges = device.logical_edges
                        if not edges:
                            pytest.skip("No 2Q edges")
                        qubits = list(edges[0])
                else:
                    qubits = [0]

                params = [math.pi / 4] * spec["params"]
                if gate_name == "id":
                    params = [100.0]

                ir = NativeGateIR(
                    target=target,
                    num_qubits=device.num_qubits,
                    gates=[GateOp(gate=gate_name, qubits=qubits, params=params)],
                    measurements=[qubits[0]],
                    metadata=_metadata(),
                )
                translated = translator.translate(ir)
                assert len(translated.program) > 0


# ===================================================================
# 2. Gate ordering
# ===================================================================


class TestGateOrdering:
    """Verify the translator preserves gate order from IR to QubiC program."""

    def test_sequential_gates_maintain_order(
        self, device: QubiCDeviceSpec
    ) -> None:
        translator = QubiCCircuitTranslator(device)
        directed = list(device.directed_cnot_edges.keys())
        ctrl, tgt = directed[0]

        ir = NativeGateIR(
            target="superconducting_cnot",
            num_qubits=device.num_qubits,
            gates=[
                GateOp(gate="x90", qubits=[ctrl], params=[]),
                GateOp(gate="virtual_z", qubits=[tgt], params=[0.5]),
                GateOp(gate="cnot", qubits=[ctrl, tgt], params=[]),
                GateOp(gate="y_minus_90", qubits=[ctrl], params=[]),
            ],
            measurements=[ctrl, tgt],
            metadata=_metadata(),
        )

        program = [
            g for g in translator.translate(ir).program if g["name"] != "read"
        ]
        ctrl_hw = device.hardware_qubit(ctrl)
        tgt_hw = device.hardware_qubit(tgt)

        x90_idx = next(
            i
            for i, g in enumerate(program)
            if g["name"] == "X90" and ctrl_hw in g["qubit"]
        )
        vz_idx = next(
            i
            for i, g in enumerate(program)
            if g["name"] == "virtual_z"
            and tgt_hw in g["qubit"]
            and g.get("phase") == 0.5
        )
        cnot_idx = next(
            i for i, g in enumerate(program) if g["name"] == "CNOT"
        )
        ym90_idx = next(
            i
            for i, g in enumerate(program)
            if g["name"] == "Y-90" and ctrl_hw in g["qubit"]
        )

        assert x90_idx < vz_idx < cnot_idx < ym90_idx

    def test_gate_qubit_targets_are_correct(
        self, device: QubiCDeviceSpec
    ) -> None:
        translator = QubiCCircuitTranslator(device)
        ir = NativeGateIR(
            target="superconducting_cnot",
            num_qubits=device.num_qubits,
            gates=[
                GateOp(gate="x90", qubits=[0], params=[]),
                GateOp(gate="y_minus_90", qubits=[1], params=[]),
                GateOp(gate="virtual_z", qubits=[2], params=[1.23]),
            ],
            measurements=[0, 1, 2],
            metadata=_metadata(),
        )

        program = [
            g for g in translator.translate(ir).program if g["name"] != "read"
        ]
        assert program[0] == {"name": "X90", "qubit": [device.hardware_qubit(0)]}
        assert program[1] == {"name": "Y-90", "qubit": [device.hardware_qubit(1)]}
        assert program[2] == {
            "name": "virtual_z",
            "phase": 1.23,
            "qubit": [device.hardware_qubit(2)],
        }

    def test_cz_decomposition_preserves_h_cnot_h_order(
        self, device: QubiCDeviceSpec
    ) -> None:
        translator = QubiCCircuitTranslator(device)
        q0, q1 = device.logical_edges[0]

        ir = NativeGateIR(
            target="superconducting_cz",
            num_qubits=device.num_qubits,
            gates=[GateOp(gate="cz", qubits=[q0, q1], params=[])],
            measurements=[q0, q1],
            metadata=_metadata(),
        )

        program = [
            g for g in translator.translate(ir).program if g["name"] != "read"
        ]
        cnot_pos = next(
            i for i, g in enumerate(program) if g["name"] == "CNOT"
        )

        pre_cnot = program[:cnot_pos]
        assert any(g["name"] == "Y-90" for g in pre_cnot)
        assert any(
            g["name"] == "virtual_z"
            and math.isclose(g["phase"], math.pi)
            for g in pre_cnot
        )

        post_cnot = program[cnot_pos + 1 :]
        assert any(g["name"] == "Y-90" for g in post_cnot)
        assert any(
            g["name"] == "virtual_z"
            and math.isclose(g["phase"], math.pi)
            for g in post_cnot
        )


# ===================================================================
# 3. Single gate operation (hardware)
# ===================================================================


class TestSingleGateOperation:
    """Single-gate circuits executed on hardware."""

    @pytest.mark.hardware
    async def test_x180_flips_qubit(
        self, hardware_runner: Any, device: QubiCDeviceSpec
    ) -> None:
        ir = NativeGateIR(
            target="superconducting_cnot",
            num_qubits=device.num_qubits,
            gates=[
                GateOp(gate="x90", qubits=[0], params=[]),
                GateOp(gate="x90", qubits=[0], params=[]),
            ],
            measurements=[0],
            metadata=_metadata(),
        )
        result = await hardware_runner.run(ir, shots=1000)
        p1 = result.counts.get("1", 0) / result.shots_completed
        assert p1 > 0.85, f"X180|0⟩ should give |1⟩, got P(1)={p1:.3f}"

    @pytest.mark.hardware
    async def test_identity_preserves_ground(
        self, hardware_runner: Any, device: QubiCDeviceSpec
    ) -> None:
        ir = NativeGateIR(
            target="superconducting_cnot",
            num_qubits=device.num_qubits,
            gates=[GateOp(gate="id", qubits=[0], params=[100.0])],
            measurements=[0],
            metadata=_metadata(),
        )
        result = await hardware_runner.run(ir, shots=1000)
        p0 = result.counts.get("0", 0) / result.shots_completed
        assert p0 > 0.85, f"Id|0⟩ should give |0⟩, got P(0)={p0:.3f}"


# ===================================================================
# 4. Bell state / 2-qubit superposition (hardware)
# ===================================================================


class TestBellStateSuperposition:
    """Verify 2-qubit entanglement via Bell-state preparation."""

    @pytest.mark.hardware
    async def test_bell_state_gives_equal_superposition(
        self, hardware_runner: Any, device: QubiCDeviceSpec
    ) -> None:
        directed = list(device.directed_cnot_edges.keys())
        ctrl, tgt = directed[0]
        ir = bell_state_circuit(
            ctrl, tgt, device.num_qubits, target="superconducting_cnot"
        )

        result = await hardware_runner.run(ir, shots=1000)
        total = result.shots_completed
        p00 = result.counts.get("00", 0) / total
        p11 = result.counts.get("11", 0) / total

        assert 0.35 < p00 < 0.65, f"P(00)={p00:.3f} outside [0.35, 0.65]"
        assert 0.35 < p11 < 0.65, f"P(11)={p11:.3f} outside [0.35, 0.65]"
        assert p00 + p11 > 0.80, (
            f"P(00)+P(11)={p00 + p11:.3f} — too much leakage to |01⟩/|10⟩"
        )


# ===================================================================
# 5. Clifford group & RB module unit tests (no hardware)
# ===================================================================


class TestCliffordGroup:
    """Verify single-qubit Clifford group algebraic properties."""

    def test_group_has_24_elements(self) -> None:
        assert len(CLIFFORD_1Q_DECOMPOSITIONS) == 24
        assert len(CLIFFORD_1Q_MATRICES) == 24

    def test_identity_is_first(self) -> None:
        assert np.allclose(CLIFFORD_1Q_MATRICES[0], np.eye(2, dtype=complex))

    def test_all_elements_are_unitary(self) -> None:
        for i, mat in enumerate(CLIFFORD_1Q_MATRICES):
            product = mat @ mat.conj().T
            assert np.allclose(
                product, np.eye(2), atol=1e-10
            ), f"Clifford {i} is not unitary"

    def test_all_elements_are_distinct(self) -> None:
        from coda_qubic.benchmarks import _matrices_equal_up_to_phase

        for i in range(24):
            for j in range(i + 1, 24):
                assert not _matrices_equal_up_to_phase(
                    CLIFFORD_1Q_MATRICES[i], CLIFFORD_1Q_MATRICES[j]
                ), f"Cliffords {i} and {j} are identical up to phase"

    def test_group_is_closed(self) -> None:
        for i in range(24):
            for j in range(24):
                k = compose_cliffords_1q(i, j)
                assert 0 <= k < 24

    def test_inverse_composition_yields_identity(self) -> None:
        for i in range(24):
            inv = clifford_1q_inverse(i)
            assert compose_cliffords_1q(i, inv) == 0

    def test_rb_sequence_ends_at_identity(self) -> None:
        import random as stdlib_random

        rng = stdlib_random.Random(42)
        for length in [1, 5, 10, 20]:
            seq = generate_rb_sequence_1q(length, rng=rng)
            assert len(seq) == length + 1
            composite = 0
            for idx in seq:
                composite = compose_cliffords_1q(composite, idx)
            assert composite == 0, f"RB sequence of length {length} not identity"

    def test_rb_ir_circuit_is_valid(self) -> None:
        import random as stdlib_random

        rng = stdlib_random.Random(42)
        seq = generate_rb_sequence_1q(5, rng=rng)
        ir = rb_ir_circuit_1q(seq, qubit=0, num_qubits=3)
        assert ir.target == "superconducting_cnot"
        assert len(ir.gates) > 0
        assert ir.measurements == [0]


class TestRBFitting:
    """Verify the RB decay fitting on synthetic data."""

    def test_fit_perfect_decay(self) -> None:
        lengths = [1, 5, 10, 20, 50, 100]
        p_true = 0.995
        probs = [0.5 * p_true**m + 0.5 for m in lengths]

        result = fit_rb_decay(lengths, probs)
        assert abs(result.depolarizing_parameter - p_true) < 0.01
        assert abs(result.average_gate_fidelity - (1 + p_true) / 2) < 0.01

    def test_fit_noisy_decay(self) -> None:
        rng = np.random.default_rng(42)
        lengths = [1, 5, 10, 20, 50, 100, 200]
        p_true = 0.98
        probs = [
            float(np.clip(0.5 * p_true**m + 0.5 + rng.normal(0, 0.01), 0, 1))
            for m in lengths
        ]

        result = fit_rb_decay(lengths, probs)
        assert 0.9 < result.depolarizing_parameter < 1.0
        assert result.average_gate_fidelity > 0.9


# ===================================================================
# 6. Randomized benchmarking (hardware)
# ===================================================================


class TestRandomizedBenchmarking:
    """Run RB experiments on hardware and compare to calibration."""

    @pytest.mark.hardware
    async def test_1q_rb_fidelity_within_tolerance(
        self, hardware_runner: Any, device: QubiCDeviceSpec
    ) -> None:
        import random as stdlib_random

        rng = stdlib_random.Random(123)
        sequence_lengths = [1, 5, 10, 20, 50]
        num_sequences = 10
        survival_probs: list[float] = []

        for m in sequence_lengths:
            successes = 0
            total = 0
            for _ in range(num_sequences):
                seq = generate_rb_sequence_1q(m, rng=rng)
                ir = rb_ir_circuit_1q(seq, qubit=0, num_qubits=device.num_qubits)
                result = await hardware_runner.run(ir, shots=100)
                successes += result.counts.get("0", 0)
                total += result.shots_completed
            survival_probs.append(successes / total)

        fit = fit_rb_decay(sequence_lengths, survival_probs)
        assert fit.average_gate_fidelity > 0.90, (
            f"1Q gate fidelity {fit.average_gate_fidelity:.4f} below 0.90"
        )


class TestTwoQubitBenchmark:
    """Two-qubit gate characterisation via CNOT truth table."""

    @pytest.mark.hardware
    async def test_cnot_truth_table_fidelity(
        self, hardware_runner: Any, device: QubiCDeviceSpec
    ) -> None:
        directed = list(device.directed_cnot_edges.keys())
        ctrl, tgt = directed[0]
        circuits = cnot_truth_table_circuits(
            ctrl, tgt, device.num_qubits
        )

        counts_list: list[dict[str, int]] = []
        expected_list: list[str] = []
        for ir, expected in circuits:
            result = await hardware_runner.run(ir, shots=1000)
            counts_list.append(result.counts)
            expected_list.append(expected)

        fidelity = cnot_average_gate_fidelity(counts_list, expected_list)
        assert fidelity > 0.80, (
            f"CNOT average gate fidelity {fidelity:.4f} below 0.80"
        )

    def test_cnot_truth_table_circuits_are_valid(
        self, device: QubiCDeviceSpec
    ) -> None:
        directed = list(device.directed_cnot_edges.keys())
        ctrl, tgt = directed[0]
        circuits = cnot_truth_table_circuits(
            ctrl, tgt, device.num_qubits
        )
        assert len(circuits) == 4
        for ir, expected in circuits:
            assert len(expected) == 2
            assert ir.target == "superconducting_cnot"

    def test_bell_state_circuit_is_valid(
        self, device: QubiCDeviceSpec
    ) -> None:
        directed = list(device.directed_cnot_edges.keys())
        ctrl, tgt = directed[0]
        ir = bell_state_circuit(ctrl, tgt, device.num_qubits)
        assert ir.target == "superconducting_cnot"
        assert len(ir.gates) == 3
        assert ir.measurements == [ctrl, tgt]

    def test_cnot_fidelity_computation(self) -> None:
        perfect_counts = [
            {"00": 1000},
            {"11": 1000},
            {"01": 1000},
            {"10": 1000},
        ]
        expected = ["00", "11", "01", "10"]
        assert cnot_average_gate_fidelity(perfect_counts, expected) == 1.0

        half_counts = [
            {"00": 500, "11": 500},
            {"11": 500, "00": 500},
            {"01": 500, "10": 500},
            {"10": 500, "01": 500},
        ]
        assert cnot_average_gate_fidelity(half_counts, expected) == 0.5
