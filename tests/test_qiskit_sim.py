from __future__ import annotations

import asyncio
import math

import pytest
from coda_node.server.executor import ExecutionResult
from coda_node.server.ir import GateOp, IRMetadata, NativeGateIR

from coda_qubic.config import QubiCConfig, RunnerMode
from coda_qubic.device import QubiCDeviceSpec
from coda_qubic.qiskit_sim import (
    QiskitNoisySimulator,
    _build_circuit,
    _reformat_counts,
    _synthesize_device_spec,
)

pytest.importorskip("qiskit")
pytest.importorskip("qiskit_aer")


def _metadata() -> IRMetadata:
    return IRMetadata(
        source_hash="sha256:test",
        compiled_at="2026-03-30T00:00:00Z",
    )


class TestBuildCircuit:
    def test_rx_gate(self):
        ir = NativeGateIR(
            num_qubits=1,
            target="cz",
            gates=[GateOp(gate="rx", qubits=[0], params=[math.pi / 4])],
            measurements=[0],
            metadata=_metadata(),
        )
        qc = _build_circuit(ir)
        assert qc.num_qubits == 1
        assert qc.num_clbits == 1

    def test_ry_gate(self):
        ir = NativeGateIR(
            num_qubits=1,
            target="cz",
            gates=[GateOp(gate="ry", qubits=[0], params=[math.pi / 2])],
            measurements=[0],
            metadata=_metadata(),
        )
        qc = _build_circuit(ir)
        assert qc.num_qubits == 1

    def test_rz_gate(self):
        ir = NativeGateIR(
            num_qubits=1,
            target="cz",
            gates=[GateOp(gate="rz", qubits=[0], params=[math.pi])],
            measurements=[0],
            metadata=_metadata(),
        )
        qc = _build_circuit(ir)
        assert qc.num_qubits == 1

    def test_cz_gate(self):
        ir = NativeGateIR(
            num_qubits=2,
            target="cz",
            gates=[GateOp(gate="cz", qubits=[0, 1])],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        qc = _build_circuit(ir)
        assert qc.num_qubits == 2
        assert qc.num_clbits == 2

    def test_cnot_gate(self):
        ir = NativeGateIR(
            num_qubits=2,
            target="cnot",
            gates=[GateOp(gate="cnot", qubits=[0, 1])],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        qc = _build_circuit(ir)
        assert qc.num_qubits == 2

    def test_x90_gate(self):
        ir = NativeGateIR(
            num_qubits=1,
            target="cnot",
            gates=[GateOp(gate="x90", qubits=[0])],
            measurements=[0],
            metadata=_metadata(),
        )
        qc = _build_circuit(ir)
        assert qc.num_qubits == 1

    def test_y_minus_90_gate(self):
        ir = NativeGateIR(
            num_qubits=1,
            target="cnot",
            gates=[GateOp(gate="y_minus_90", qubits=[0])],
            measurements=[0],
            metadata=_metadata(),
        )
        qc = _build_circuit(ir)
        assert qc.num_qubits == 1

    def test_virtual_z_gate(self):
        ir = NativeGateIR(
            num_qubits=1,
            target="cnot",
            gates=[GateOp(gate="virtual_z", qubits=[0], params=[math.pi / 3])],
            measurements=[0],
            metadata=_metadata(),
        )
        qc = _build_circuit(ir)
        assert qc.num_qubits == 1

    def test_id_gate(self):
        ir = NativeGateIR(
            num_qubits=1,
            target="cz",
            gates=[GateOp(gate="id", qubits=[0], params=[100.0])],
            measurements=[0],
            metadata=_metadata(),
        )
        qc = _build_circuit(ir)
        assert qc.num_qubits == 1

    def test_measurement_maps_to_classical_bits(self):
        ir = NativeGateIR(
            num_qubits=3,
            target="cz",
            gates=[GateOp(gate="rx", qubits=[0], params=[math.pi])],
            measurements=[2, 0],
            metadata=_metadata(),
        )
        qc = _build_circuit(ir)
        assert qc.num_qubits == 3
        assert qc.num_clbits == 2

    def test_multi_gate_circuit(self):
        ir = NativeGateIR(
            num_qubits=2,
            target="cz",
            gates=[
                GateOp(gate="rx", qubits=[0], params=[math.pi]),
                GateOp(gate="cz", qubits=[0, 1]),
                GateOp(gate="rz", qubits=[1], params=[math.pi / 2]),
            ],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        qc = _build_circuit(ir)
        assert qc.num_qubits == 2
        assert qc.num_clbits == 2


class TestReformatCounts:
    def test_passthrough(self):
        raw = {"00": 5, "11": 3}
        result = _reformat_counts(raw, [0, 1])
        assert result == {"00": 5, "11": 3}

    def test_strips_whitespace(self):
        raw = {"0 0": 5, "1 1": 3}
        result = _reformat_counts(raw, [0, 1])
        assert result == {"00": 5, "11": 3}

    def test_rejects_width_mismatch(self):
        raw = {"000": 5}
        with pytest.raises(Exception, match="width"):
            _reformat_counts(raw, [0, 1])


class TestSynthesizeDeviceSpec:
    def test_single_qubit(self):
        device = _synthesize_device_spec(1)
        assert device.num_qubits == 1
        assert device.logical_to_hardware == ("Q1",)
        assert device.directed_cnot_edges == {}

    def test_three_qubits_linear_chain(self):
        device = _synthesize_device_spec(3)
        assert device.num_qubits == 3
        assert device.logical_to_hardware == ("Q1", "Q2", "Q3")
        assert len(device.directed_cnot_edges) == 2
        assert (1, 0) in device.directed_cnot_edges
        assert (2, 1) in device.directed_cnot_edges

    def test_qubit_calibrations_present(self):
        device = _synthesize_device_spec(4)
        assert len(device.qubits) == 4
        for logical in range(4):
            cal = device.qubits[logical]
            assert cal.logical_qubit == logical
            assert cal.hardware_qubit == f"Q{logical + 1}"
            assert cal.drive_frequency_hz > 0
            assert cal.readout_frequency_hz > 0


class TestQiskitNoisySimulator:
    def test_device_property(self):
        sim = QiskitNoisySimulator(num_qubits=3, target="cnot")
        assert isinstance(sim.device, QubiCDeviceSpec)
        assert sim.device.num_qubits == 3

    def test_run_returns_execution_result(self):
        sim = QiskitNoisySimulator(
            num_qubits=2,
            target="cz",
            single_qubit_error_rate=0.0,
            two_qubit_error_rate=0.0,
            measurement_error_rate=0.0,
        )
        ir = NativeGateIR(
            num_qubits=2,
            target="cz",
            gates=[],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        result = asyncio.run(sim.run(ir, 100))
        assert isinstance(result, ExecutionResult)
        assert result.shots_completed == 100
        assert sum(result.counts.values()) == 100
        assert all(len(k) == 2 for k in result.counts)

    def test_noiseless_bell_state(self):
        sim = QiskitNoisySimulator(
            num_qubits=2,
            target="cz",
            single_qubit_error_rate=0.0,
            two_qubit_error_rate=0.0,
            measurement_error_rate=0.0,
        )
        ir = NativeGateIR(
            num_qubits=2,
            target="cz",
            gates=[
                GateOp(gate="ry", qubits=[0], params=[math.pi / 2]),
                GateOp(gate="rx", qubits=[0], params=[math.pi]),
                GateOp(gate="cz", qubits=[0, 1]),
                GateOp(gate="ry", qubits=[0], params=[math.pi / 2]),
                GateOp(gate="rx", qubits=[0], params=[math.pi]),
            ],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        result = asyncio.run(sim.run(ir, 1000))
        assert "00" in result.counts or "11" in result.counts
        unexpected = result.counts.get("01", 0) + result.counts.get("10", 0)
        assert unexpected == 0

    def test_noisy_simulation_produces_varied_results(self):
        sim = QiskitNoisySimulator(
            num_qubits=1,
            target="cz",
            single_qubit_error_rate=0.1,
            two_qubit_error_rate=0.1,
            measurement_error_rate=0.1,
        )
        ir = NativeGateIR(
            num_qubits=1,
            target="cz",
            gates=[],
            measurements=[0],
            metadata=_metadata(),
        )
        result = asyncio.run(sim.run(ir, 10000))
        assert len(result.counts) > 0
        assert sum(result.counts.values()) == 10000

    def test_target_mismatch_raises(self):
        sim = QiskitNoisySimulator(num_qubits=2, target="cnot")
        ir = NativeGateIR(
            num_qubits=2,
            target="cz",
            gates=[],
            measurements=[0],
            metadata=_metadata(),
        )
        with pytest.raises(Exception, match="target mismatch"):
            asyncio.run(sim.run(ir, 10))

    def test_qubit_count_exceeded_raises(self):
        sim = QiskitNoisySimulator(num_qubits=2, target="cz")
        ir = NativeGateIR(
            num_qubits=5,
            target="cz",
            gates=[],
            measurements=[0],
            metadata=_metadata(),
        )
        with pytest.raises(Exception, match="qubits"):
            asyncio.run(sim.run(ir, 10))

    def test_zero_noise_rates_accepted(self):
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
            gates=[],
            measurements=[0],
            metadata=_metadata(),
        )
        result = asyncio.run(sim.run(ir, 100))
        assert result.counts == {"0": 100}

    def test_cancel_current_job_forwards_to_active_aer_job(self):
        sim = QiskitNoisySimulator(num_qubits=1, target="cz")

        class FakeJob:
            def __init__(self) -> None:
                self.cancel_calls = 0

            def cancel(self) -> None:
                self.cancel_calls += 1

        job = FakeJob()
        sim.__dict__["_current_job"] = job

        sim.cancel_current_job()

        assert job.cancel_calls == 1


class TestConfigQiskitSim:
    def test_qiskit_sim_mode_no_calibration_paths(self):
        config = QubiCConfig(
            target="cnot",
            num_qubits=3,
            runner_mode="qiskit_sim",
        )
        assert config.runner_mode == RunnerMode.QISKIT_SIM
        assert config.calibration_path == ""

    def test_qiskit_sim_with_noise_params(self):
        config = QubiCConfig(
            target="cnot",
            num_qubits=3,
            runner_mode="qiskit_sim",
            single_qubit_error_rate=0.005,
            two_qubit_error_rate=0.05,
            measurement_error_rate=0.02,
        )
        assert config.single_qubit_error_rate == 0.005
        assert config.two_qubit_error_rate == 0.05
        assert config.measurement_error_rate == 0.02

    def test_non_qiskit_mode_requires_calibration_path(self):
        with pytest.raises(ValueError, match="calibration_path is required"):
            QubiCConfig(
                target="cnot",
                num_qubits=3,
                runner_mode="local",
                use_sim=True,
            )

    def test_non_qiskit_mode_requires_channel_config_path(self):
        with pytest.raises(ValueError, match="channel_config_path is required"):
            QubiCConfig(
                target="cnot",
                num_qubits=3,
                calibration_path="/tmp/cal.json",
                runner_mode="local",
                use_sim=True,
            )

    def test_non_qiskit_mode_requires_classifier_path(self):
        with pytest.raises(ValueError, match="classifier_path is required"):
            QubiCConfig(
                target="cnot",
                num_qubits=3,
                calibration_path="/tmp/cal.json",
                channel_config_path="/tmp/chan.json",
                runner_mode="local",
                use_sim=True,
            )
