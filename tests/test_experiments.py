"""Tests for T1, T2 Ramsey, and T2 Echo characterization experiments.

Covers circuit construction validity, translator compatibility, decay
fitting on synthetic data, and end-to-end simulation via QiskitNoisySimulator.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

import numpy as np
import pytest
from coda_node.server.ir import GateOp, IRMetadata, NativeGateIR

from coda_qubic.device import QubiCDeviceSpec
from coda_qubic.experiments import (
    T1FitResult,
    T2FitResult,
    fit_t1_decay,
    fit_t2_decay,
    t1_circuits,
    t2_echo_circuits,
    t2_ramsey_circuits,
)
from coda_qubic.translator import QubiCCircuitTranslator


def _metadata() -> IRMetadata:
    return IRMetadata(
        source_hash="sha256:test-experiment",
        compiled_at="2026-03-31T00:00:00Z",
    )


# ===================================================================
# 1. T1 circuit construction
# ===================================================================


class TestT1Circuits:
    def test_returns_correct_number_of_circuits(self) -> None:
        delays = [100.0, 500.0, 1000.0, 2000.0]
        circuits = t1_circuits(qubit=0, num_qubits=1, delay_times_ns=delays)
        assert len(circuits) == len(delays)

    def test_delay_values_are_preserved(self) -> None:
        delays = [0.0, 250.0, 750.0]
        circuits = t1_circuits(qubit=0, num_qubits=1, delay_times_ns=delays)
        for (_, delay_ns), expected in zip(circuits, delays, strict=True):
            assert delay_ns == expected

    def test_cnot_target_uses_native_gates(self) -> None:
        circuits = t1_circuits(
            qubit=0, num_qubits=1, delay_times_ns=[500.0], target="cnot"
        )
        ir, _ = circuits[0]
        assert ir.target == "cnot"
        gate_names = [g.gate.value for g in ir.gates]
        assert gate_names.count("x90") == 2
        assert "id" in gate_names

    def test_cz_target_uses_rx_gates(self) -> None:
        circuits = t1_circuits(
            qubit=0, num_qubits=1, delay_times_ns=[500.0], target="cz"
        )
        ir, _ = circuits[0]
        assert ir.target == "cz"
        gate_names = [g.gate.value for g in ir.gates]
        assert "rx" in gate_names
        assert "id" in gate_names

    def test_cz_target_rx_has_pi_angle(self) -> None:
        circuits = t1_circuits(
            qubit=0, num_qubits=1, delay_times_ns=[500.0], target="cz"
        )
        ir, _ = circuits[0]
        rx_gates = [g for g in ir.gates if g.gate.value == "rx"]
        assert len(rx_gates) == 1
        assert math.isclose(rx_gates[0].params[0], math.pi)

    def test_delay_duration_in_id_gate(self) -> None:
        circuits = t1_circuits(
            qubit=0, num_qubits=1, delay_times_ns=[1234.5], target="cnot"
        )
        ir, _ = circuits[0]
        id_gates = [g for g in ir.gates if g.gate.value == "id"]
        assert len(id_gates) == 1
        assert id_gates[0].params[0] == 1234.5

    def test_measures_correct_qubit(self) -> None:
        circuits = t1_circuits(
            qubit=2, num_qubits=4, delay_times_ns=[100.0], target="cnot"
        )
        ir, _ = circuits[0]
        assert ir.measurements == [2]

    def test_ir_is_valid_native_gate_ir(self) -> None:
        circuits = t1_circuits(
            qubit=0, num_qubits=3, delay_times_ns=[100.0, 500.0], target="cnot"
        )
        for ir, _ in circuits:
            assert isinstance(ir, NativeGateIR)
            assert ir.num_qubits == 3

    def test_translates_on_device(
        self, qubic_example_qubitcfg_path: Path
    ) -> None:
        device = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        translator = QubiCCircuitTranslator(device)
        circuits = t1_circuits(
            qubit=0,
            num_qubits=device.num_qubits,
            delay_times_ns=[100.0, 500.0, 1000.0],
            target="cnot",
        )
        for ir, _ in circuits:
            translated = translator.translate(ir)
            assert len(translated.program) > 0
            delay_instrs = [
                g for g in translated.program if g["name"] == "delay"
            ]
            assert len(delay_instrs) == 1


# ===================================================================
# 2. T2 Ramsey circuit construction
# ===================================================================


class TestT2RamseyCircuits:
    def test_returns_correct_number_of_circuits(self) -> None:
        delays = [100.0, 500.0, 1000.0]
        circuits = t2_ramsey_circuits(qubit=0, num_qubits=1, delay_times_ns=delays)
        assert len(circuits) == len(delays)

    def test_cnot_target_has_two_x90_gates(self) -> None:
        circuits = t2_ramsey_circuits(
            qubit=0, num_qubits=1, delay_times_ns=[500.0], target="cnot"
        )
        ir, _ = circuits[0]
        gate_names = [g.gate.value for g in ir.gates]
        assert gate_names.count("x90") == 2
        assert gate_names.count("id") == 1

    def test_cz_target_has_two_rx_half_pi(self) -> None:
        circuits = t2_ramsey_circuits(
            qubit=0, num_qubits=1, delay_times_ns=[500.0], target="cz"
        )
        ir, _ = circuits[0]
        rx_gates = [g for g in ir.gates if g.gate.value == "rx"]
        assert len(rx_gates) == 2
        for g in rx_gates:
            assert math.isclose(g.params[0], math.pi / 2)

    def test_gate_order_is_x90_delay_x90(self) -> None:
        circuits = t2_ramsey_circuits(
            qubit=0, num_qubits=1, delay_times_ns=[500.0], target="cnot"
        )
        ir, _ = circuits[0]
        gate_names = [g.gate.value for g in ir.gates]
        assert gate_names == ["x90", "id", "x90"]

    def test_delay_value_matches(self) -> None:
        circuits = t2_ramsey_circuits(
            qubit=0, num_qubits=1, delay_times_ns=[777.0], target="cnot"
        )
        ir, _ = circuits[0]
        id_gate = next(g for g in ir.gates if g.gate.value == "id")
        assert id_gate.params[0] == 777.0

    def test_translates_on_device(
        self, qubic_example_qubitcfg_path: Path
    ) -> None:
        device = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        translator = QubiCCircuitTranslator(device)
        circuits = t2_ramsey_circuits(
            qubit=0,
            num_qubits=device.num_qubits,
            delay_times_ns=[100.0, 500.0],
            target="cnot",
        )
        for ir, _ in circuits:
            translated = translator.translate(ir)
            assert len(translated.program) > 0


# ===================================================================
# 3. T2 Echo circuit construction
# ===================================================================


class TestT2EchoCircuits:
    def test_returns_correct_number_of_circuits(self) -> None:
        delays = [200.0, 600.0, 1200.0]
        circuits = t2_echo_circuits(qubit=0, num_qubits=1, delay_times_ns=delays)
        assert len(circuits) == len(delays)

    def test_cnot_target_gate_structure(self) -> None:
        circuits = t2_echo_circuits(
            qubit=0, num_qubits=1, delay_times_ns=[1000.0], target="cnot"
        )
        ir, _ = circuits[0]
        gate_names = [g.gate.value for g in ir.gates]
        # X90, delay, X90, X90 (=X180), delay, X90
        assert gate_names == ["x90", "id", "x90", "x90", "id", "x90"]

    def test_cz_target_gate_structure(self) -> None:
        circuits = t2_echo_circuits(
            qubit=0, num_qubits=1, delay_times_ns=[1000.0], target="cz"
        )
        ir, _ = circuits[0]
        gate_names = [g.gate.value for g in ir.gates]
        # rx(π/2), delay, rx(π), delay, rx(π/2)
        assert gate_names == ["rx", "id", "rx", "id", "rx"]

    def test_delay_is_split_in_half(self) -> None:
        total_delay = 1000.0
        circuits = t2_echo_circuits(
            qubit=0, num_qubits=1, delay_times_ns=[total_delay], target="cnot"
        )
        ir, _ = circuits[0]
        id_gates = [g for g in ir.gates if g.gate.value == "id"]
        assert len(id_gates) == 2
        for g in id_gates:
            assert g.params[0] == total_delay / 2.0

    def test_cz_target_rx_angles(self) -> None:
        circuits = t2_echo_circuits(
            qubit=0, num_qubits=1, delay_times_ns=[1000.0], target="cz"
        )
        ir, _ = circuits[0]
        rx_gates = [g for g in ir.gates if g.gate.value == "rx"]
        angles = [g.params[0] for g in rx_gates]
        assert math.isclose(angles[0], math.pi / 2)
        assert math.isclose(angles[1], math.pi)
        assert math.isclose(angles[2], math.pi / 2)

    def test_translates_on_device(
        self, qubic_example_qubitcfg_path: Path
    ) -> None:
        device = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        translator = QubiCCircuitTranslator(device)
        circuits = t2_echo_circuits(
            qubit=0,
            num_qubits=device.num_qubits,
            delay_times_ns=[200.0, 800.0],
            target="cnot",
        )
        for ir, _ in circuits:
            translated = translator.translate(ir)
            assert len(translated.program) > 0
            delay_instrs = [
                g for g in translated.program if g["name"] == "delay"
            ]
            assert len(delay_instrs) == 2


# ===================================================================
# 4. T1 decay fitting
# ===================================================================


class TestT1Fitting:
    def test_fit_perfect_exponential(self) -> None:
        t1_true = 5000.0
        delays = [0.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 12000.0]
        probs = [1.0 * np.exp(-t / t1_true) for t in delays]

        result = fit_t1_decay(delays, probs)
        assert isinstance(result, T1FitResult)
        assert abs(result.t1_ns - t1_true) / t1_true < 0.05

    def test_fit_with_offset(self) -> None:
        t1_true = 3000.0
        a_true = 0.9
        b_true = 0.05
        delays = [0.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0]
        probs = [a_true * np.exp(-t / t1_true) + b_true for t in delays]

        result = fit_t1_decay(delays, probs)
        assert abs(result.t1_ns - t1_true) / t1_true < 0.05
        assert abs(result.fit_amplitude - a_true) < 0.05
        assert abs(result.fit_offset - b_true) < 0.05

    def test_fit_noisy_data(self) -> None:
        rng = np.random.default_rng(42)
        t1_true = 10000.0
        delays = [0.0, 1000.0, 2000.0, 5000.0, 10000.0, 20000.0, 30000.0]
        probs = [
            float(np.clip(0.9 * np.exp(-t / t1_true) + 0.05 + rng.normal(0, 0.02), 0, 1))
            for t in delays
        ]

        result = fit_t1_decay(delays, probs)
        assert 0.5 * t1_true < result.t1_ns < 2.0 * t1_true


# ===================================================================
# 5. T2 decay fitting
# ===================================================================


class TestT2Fitting:
    def test_fit_pure_exponential(self) -> None:
        t2_true = 3000.0
        delays = [0.0, 300.0, 600.0, 1000.0, 2000.0, 4000.0, 8000.0]
        probs = [0.5 * np.exp(-t / t2_true) + 0.5 for t in delays]

        result = fit_t2_decay(delays, probs, with_oscillation=False)
        assert isinstance(result, T2FitResult)
        assert abs(result.t2_ns - t2_true) / t2_true < 0.05
        assert result.frequency_hz == 0.0

    def test_fit_with_offset(self) -> None:
        t2_true = 5000.0
        a_true = 0.45
        b_true = 0.5
        delays = [0.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0]
        probs = [a_true * np.exp(-t / t2_true) + b_true for t in delays]

        result = fit_t2_decay(delays, probs, with_oscillation=False)
        assert abs(result.t2_ns - t2_true) / t2_true < 0.05

    def test_fit_noisy_exponential(self) -> None:
        rng = np.random.default_rng(123)
        t2_true = 4000.0
        delays = [0.0, 400.0, 800.0, 1500.0, 3000.0, 6000.0, 10000.0]
        probs = [
            float(np.clip(0.5 * np.exp(-t / t2_true) + 0.5 + rng.normal(0, 0.02), 0, 1))
            for t in delays
        ]

        result = fit_t2_decay(delays, probs, with_oscillation=False)
        assert 0.5 * t2_true < result.t2_ns < 2.0 * t2_true

    def test_fit_with_oscillation(self) -> None:
        t2_true = 5000.0
        f_true = 5e-5  # in 1/ns
        delays = np.linspace(0, 15000, 60).tolist()
        probs = [
            float(0.45 * np.exp(-t / t2_true) * np.cos(2 * np.pi * f_true * t) + 0.5)
            for t in delays
        ]

        result = fit_t2_decay(delays, probs, with_oscillation=True)
        assert abs(result.t2_ns - t2_true) / t2_true < 0.15
        assert result.frequency_hz > 0


# ===================================================================
# 6. Qiskit simulation integration tests
# ===================================================================


qiskit = pytest.importorskip("qiskit")
pytest.importorskip("qiskit_aer")

from coda_qubic.qiskit_sim import QiskitNoisySimulator, _build_circuit


class TestQiskitSimThermalRelaxation:
    """Verify that the Qiskit simulator's thermal relaxation produces
    measurable T1/T2 decay when running characterization circuits."""

    def test_build_circuit_with_relaxation_inserts_instructions(self) -> None:
        ir = NativeGateIR(
            num_qubits=1,
            target="cz",
            gates=[
                GateOp(gate="rx", qubits=[0], params=[math.pi]),
                GateOp(gate="id", qubits=[0], params=[1000.0]),
            ],
            measurements=[0],
            metadata=_metadata(),
        )
        qc_no_relax = _build_circuit(ir)
        qc_relax = _build_circuit(ir, t1_ns=5000.0, t2_ns=3000.0)

        no_relax_ops = [inst.operation.name for inst in qc_no_relax]
        relax_ops = [inst.operation.name for inst in qc_relax]

        assert "id" in no_relax_ops
        assert "id" not in relax_ops
        assert any("kraus" in name or "superop" in name or name not in ("rx", "measure")
                    for name in relax_ops if name not in ("rx", "measure"))

    def test_build_circuit_without_relaxation_uses_id(self) -> None:
        ir = NativeGateIR(
            num_qubits=1,
            target="cz",
            gates=[GateOp(gate="id", qubits=[0], params=[100.0])],
            measurements=[0],
            metadata=_metadata(),
        )
        qc = _build_circuit(ir)
        op_names = [inst.operation.name for inst in qc]
        assert "id" in op_names

    def test_zero_delay_uses_id_even_with_relaxation(self) -> None:
        ir = NativeGateIR(
            num_qubits=1,
            target="cz",
            gates=[GateOp(gate="id", qubits=[0], params=[0.0])],
            measurements=[0],
            metadata=_metadata(),
        )
        qc = _build_circuit(ir, t1_ns=5000.0, t2_ns=3000.0)
        op_names = [inst.operation.name for inst in qc]
        assert "id" in op_names

    def test_t1_decay_visible_in_simulation(self) -> None:
        t1_ns = 5000.0
        t2_ns = 8000.0
        sim = QiskitNoisySimulator(
            num_qubits=1,
            target="cz",
            single_qubit_error_rate=0.0,
            two_qubit_error_rate=0.0,
            measurement_error_rate=0.0,
            t1_ns=t1_ns,
            t2_ns=t2_ns,
        )

        delays = [0.0, 1000.0, 2000.0, 4000.0, 8000.0, 15000.0]
        circuits = t1_circuits(
            qubit=0, num_qubits=1, delay_times_ns=delays, target="cz"
        )

        probs: list[float] = []
        for ir, _ in circuits:
            result = asyncio.run(sim.run(ir, 2000))
            p1 = result.counts.get("1", 0) / result.shots_completed
            probs.append(p1)

        assert probs[0] > 0.8, f"P(1) at t=0 should be near 1.0, got {probs[0]:.3f}"
        assert probs[-1] < probs[0], (
            f"P(1) should decay: t=0 gave {probs[0]:.3f}, "
            f"t={delays[-1]} gave {probs[-1]:.3f}"
        )

    def test_t1_fit_from_simulation(self) -> None:
        t1_ns = 5000.0
        t2_ns = 8000.0
        sim = QiskitNoisySimulator(
            num_qubits=1,
            target="cz",
            single_qubit_error_rate=0.0,
            two_qubit_error_rate=0.0,
            measurement_error_rate=0.0,
            t1_ns=t1_ns,
            t2_ns=t2_ns,
        )

        delays = [0.0, 500.0, 1000.0, 2000.0, 3000.0, 5000.0, 8000.0, 12000.0]
        circuits = t1_circuits(
            qubit=0, num_qubits=1, delay_times_ns=delays, target="cz"
        )

        probs: list[float] = []
        for ir, _ in circuits:
            result = asyncio.run(sim.run(ir, 4000))
            p1 = result.counts.get("1", 0) / result.shots_completed
            probs.append(p1)

        fit = fit_t1_decay(delays, probs)
        assert 0.3 * t1_ns < fit.t1_ns < 3.0 * t1_ns, (
            f"Fitted T1={fit.t1_ns:.0f} ns, expected ~{t1_ns:.0f} ns"
        )

    def test_t2_echo_decay_visible_in_simulation(self) -> None:
        t1_ns = 20000.0
        t2_ns = 5000.0
        sim = QiskitNoisySimulator(
            num_qubits=1,
            target="cz",
            single_qubit_error_rate=0.0,
            two_qubit_error_rate=0.0,
            measurement_error_rate=0.0,
            t1_ns=t1_ns,
            t2_ns=t2_ns,
        )

        delays = [0.0, 1000.0, 2000.0, 4000.0, 8000.0, 15000.0]
        circuits = t2_echo_circuits(
            qubit=0, num_qubits=1, delay_times_ns=delays, target="cz"
        )

        probs: list[float] = []
        for ir, _ in circuits:
            result = asyncio.run(sim.run(ir, 2000))
            p0 = result.counts.get("0", 0) / result.shots_completed
            probs.append(p0)

        assert probs[-1] < probs[0], (
            f"P(0) should decay: t=0 gave {probs[0]:.3f}, "
            f"t={delays[-1]} gave {probs[-1]:.3f}"
        )

    def test_t2_ramsey_decay_visible_in_simulation(self) -> None:
        t1_ns = 20000.0
        t2_ns = 5000.0
        sim = QiskitNoisySimulator(
            num_qubits=1,
            target="cz",
            single_qubit_error_rate=0.0,
            two_qubit_error_rate=0.0,
            measurement_error_rate=0.0,
            t1_ns=t1_ns,
            t2_ns=t2_ns,
        )

        delays = [0.0, 1000.0, 2000.0, 4000.0, 8000.0, 15000.0]
        circuits = t2_ramsey_circuits(
            qubit=0, num_qubits=1, delay_times_ns=delays, target="cz"
        )

        # For on-resonance Ramsey (X90 → delay → X90), at t=0 the two
        # π/2 pulses combine into a π pulse: P(1) ≈ 1.  With dephasing,
        # P(1) decays toward 0.5.
        probs: list[float] = []
        for ir, _ in circuits:
            result = asyncio.run(sim.run(ir, 2000))
            p1 = result.counts.get("1", 0) / result.shots_completed
            probs.append(p1)

        assert probs[0] > 0.8, (
            f"P(1) at t=0 should be near 1.0, got {probs[0]:.3f}"
        )
        assert probs[-1] < probs[0], (
            f"P(1) should decay: t=0 gave {probs[0]:.3f}, "
            f"t={delays[-1]} gave {probs[-1]:.3f}"
        )

    def test_simulator_backward_compatible_without_relaxation(self) -> None:
        sim = QiskitNoisySimulator(
            num_qubits=1,
            target="cz",
            single_qubit_error_rate=0.0,
            two_qubit_error_rate=0.0,
            measurement_error_rate=0.0,
        )
        ir = NativeGateIR(
            num_qubits=1,
            target="cz",
            gates=[GateOp(gate="id", qubits=[0], params=[100.0])],
            measurements=[0],
            metadata=_metadata(),
        )
        result = asyncio.run(sim.run(ir, 100))
        assert result.counts == {"0": 100}

    def test_cnot_target_t1_circuits_simulate(self) -> None:
        sim = QiskitNoisySimulator(
            num_qubits=1,
            target="cnot",
            single_qubit_error_rate=0.0,
            two_qubit_error_rate=0.0,
            measurement_error_rate=0.0,
            t1_ns=5000.0,
            t2_ns=3000.0,
        )
        circuits = t1_circuits(
            qubit=0, num_qubits=1, delay_times_ns=[0.0, 2000.0], target="cnot"
        )
        for ir, _ in circuits:
            result = asyncio.run(sim.run(ir, 100))
            assert sum(result.counts.values()) == 100
