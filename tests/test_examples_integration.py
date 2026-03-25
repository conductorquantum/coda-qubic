"""Integration tests with real example configuration files."""

from __future__ import annotations

from pathlib import Path

from self_service.server.ir import GateOp, IRMetadata, NativeGateIR

from coda_qubic.config import QubiCConfig
from coda_qubic.device import QubiCDeviceSpec
from coda_qubic.framework import QubiCFramework
from coda_qubic.translator import QubiCCircuitTranslator

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


class TestRealConfigurationFiles:
    """Test with actual example configuration files from the repo."""

    def test_real_qubitcfg_loads_and_derives_device(self):
        """Verify real qubitcfg.json loads and derives the 20-qubit sparse-grid device."""
        qubitcfg_path = EXAMPLES_DIR / "qubitcfg.json"
        assert qubitcfg_path.exists(), "Example qubitcfg.json not found"

        device = QubiCDeviceSpec.from_qubitcfg(qubitcfg_path)

        assert device.num_qubits == 20
        assert device.logical_to_hardware == tuple(f"Q{i}" for i in range(20))
        assert len(device.logical_edges) == 24
        assert (0, 1) in device.logical_edges
        assert (5, 6) in device.logical_edges
        assert (18, 19) in device.logical_edges
        assert len(device.directed_cnot_edges) == 24

    def test_real_device_configs_validate(self):
        """Verify all example device YAML files load as valid QubiCConfig."""
        configs = [
            "device_sim.yaml",
            "device_rpc.yaml",
            "device_hardware.yaml",
        ]

        for config_name in configs:
            config_path = EXAMPLES_DIR / config_name
            assert config_path.exists(), f"Example {config_name} not found"

            config = QubiCConfig.from_yaml(str(config_path))
            assert config.target in ("cz", "cnot")

    def test_translation_with_real_calibration(self):
        """Test circuit translation using real calibration parameters."""
        qubitcfg_path = EXAMPLES_DIR / "qubitcfg.json"
        device = QubiCDeviceSpec.from_qubitcfg(qubitcfg_path)

        ir = NativeGateIR(
            num_qubits=20,
            target="cnot",
            gates=[
                GateOp(gate="x90", qubits=[0], params=[]),
                GateOp(gate="y_minus_90", qubits=[5], params=[]),
                GateOp(gate="virtual_z", qubits=[10], params=[1.5708]),
                GateOp(gate="cnot", qubits=[1, 0], params=[]),
                GateOp(gate="cnot", qubits=[6, 5], params=[]),
            ],
            measurements=[0, 5, 10],
            metadata=IRMetadata(
                source_hash="test",
                compiled_at="2026-03-16T00:00:00Z",
            ),
        )

        translator = QubiCCircuitTranslator(device)
        translated = translator.translate(ir)

        assert len(translated.program) == 8  # 5 gates + 3 measurements
        assert translated.measurement_hardware_order == ["Q0", "Q5", "Q10"]

        assert translated.program[0] == {"name": "X90", "qubit": ["Q0"]}
        assert translated.program[1] == {"name": "Y-90", "qubit": ["Q5"]}
        assert translated.program[2] == {
            "name": "virtual_z",
            "phase": 1.5708,
            "qubit": ["Q10"],
        }
        assert translated.program[3] == {"name": "CNOT", "qubit": ["Q1", "Q0"]}
        assert translated.program[4] == {"name": "CNOT", "qubit": ["Q6", "Q5"]}

    def test_cz_circuit_with_real_calibration(self):
        """Test CZ circuit translation with real device."""
        qubitcfg_path = EXAMPLES_DIR / "qubitcfg.json"
        device = QubiCDeviceSpec.from_qubitcfg(qubitcfg_path)

        ir = NativeGateIR(
            num_qubits=20,
            target="cz",
            gates=[
                GateOp(gate="rx", qubits=[0], params=[1.5708]),
                GateOp(gate="cz", qubits=[0, 1], params=[]),
            ],
            measurements=[0, 1],
            metadata=IRMetadata(
                source_hash="test",
                compiled_at="2026-03-16T00:00:00Z",
            ),
        )

        translator = QubiCCircuitTranslator(device)
        translated = translator.translate(ir)

        assert {"name": "CNOT", "qubit": ["Q1", "Q0"]} in translated.program
        y90_instructions = [
            instr for instr in translated.program if instr.get("name") == "Y-90"
        ]
        assert len(y90_instructions) == 2  # H before and after CNOT

    def test_real_calibration_parameters(self):
        """Verify real calibration parameters are reasonable."""
        qubitcfg_path = EXAMPLES_DIR / "qubitcfg.json"
        device = QubiCDeviceSpec.from_qubitcfg(qubitcfg_path)

        q0 = device.qubits[0]
        assert q0.hardware_qubit == "Q0"
        assert 4e9 < q0.drive_frequency_hz < 6e9
        assert 6e9 < q0.readout_frequency_hz < 8e9
        assert 0 < q0.x90_duration_ns < 100
        assert 0 < q0.readout_duration_ns < 5000

        cnot = device.directed_cnot_edges[(1, 0)]
        assert cnot.control_hardware == "Q1"
        assert cnot.target_hardware == "Q0"
        assert 0 < cnot.cr_duration_ns < 1000
        assert 0 < cnot.target_pulse_duration_ns < 200

        for qid in range(20):
            q = device.qubits[qid]
            assert 4e9 < q.drive_frequency_hz < 6e9
            assert 6e9 < q.readout_frequency_hz < 8e9

    def test_framework_methods_with_real_config(self):
        """Verify framework implementation with real config."""
        framework = QubiCFramework()

        assert framework.name == "qubic"
        assert "cz" in framework.supported_targets
        assert "cnot" in framework.supported_targets
