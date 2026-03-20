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
        """Verify real qubitcfg.json loads and derives correct device."""
        qubitcfg_path = EXAMPLES_DIR / "qubitcfg.json"
        assert qubitcfg_path.exists(), "Example qubitcfg.json not found"

        device = QubiCDeviceSpec.from_qubitcfg(qubitcfg_path)

        # The real config should derive Q1, Q2, Q3 as largest connected component
        assert device.num_qubits == 3
        assert device.logical_to_hardware == ("Q1", "Q2", "Q3")
        assert device.logical_edges == [(0, 1), (1, 2)]
        assert sorted(device.directed_cnot_edges.keys()) == [(1, 0), (2, 1)]

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
            assert config.target in ("superconducting_cz", "superconducting_cnot")

    def test_translation_with_real_calibration(self):
        """Test circuit translation using real calibration parameters."""
        qubitcfg_path = EXAMPLES_DIR / "qubitcfg.json"
        device = QubiCDeviceSpec.from_qubitcfg(qubitcfg_path)

        # Create a circuit using all 3 qubits
        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cnot",
            gates=[
                GateOp(gate="x90", qubits=[0], params=[]),
                GateOp(gate="y_minus_90", qubits=[1], params=[]),
                GateOp(gate="virtual_z", qubits=[2], params=[1.5708]),
                GateOp(gate="cnot", qubits=[1, 0], params=[]),
                GateOp(gate="cnot", qubits=[2, 1], params=[]),
            ],
            measurements=[0, 1, 2],
            metadata=IRMetadata(
                source_hash="test",
                compiled_at="2026-03-16T00:00:00Z",
            ),
        )

        translator = QubiCCircuitTranslator(device)
        translated = translator.translate(ir)

        # Verify translation
        assert len(translated.program) == 8  # 5 gates + 3 measurements
        assert translated.measurement_hardware_order == ["Q1", "Q2", "Q3"]

        # Check specific instructions
        assert translated.program[0] == {"name": "X90", "qubit": ["Q1"]}
        assert translated.program[1] == {"name": "Y-90", "qubit": ["Q2"]}
        assert translated.program[2] == {
            "name": "virtual_z",
            "phase": 1.5708,
            "qubit": ["Q3"],
        }
        assert translated.program[3] == {"name": "CNOT", "qubit": ["Q2", "Q1"]}
        assert translated.program[4] == {"name": "CNOT", "qubit": ["Q3", "Q2"]}

    def test_cz_circuit_with_real_calibration(self):
        """Test CZ circuit translation with real device."""
        qubitcfg_path = EXAMPLES_DIR / "qubitcfg.json"
        device = QubiCDeviceSpec.from_qubitcfg(qubitcfg_path)

        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cz",
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

        # CZ should be lowered to H-CNOT-H
        assert {"name": "CNOT", "qubit": ["Q2", "Q1"]} in translated.program
        # Should have Y-90 gates for Hadamards
        y90_instructions = [
            instr for instr in translated.program if instr.get("name") == "Y-90"
        ]
        assert len(y90_instructions) == 2  # H before and after CNOT

    def test_real_calibration_parameters(self):
        """Verify real calibration parameters are reasonable."""
        qubitcfg_path = EXAMPLES_DIR / "qubitcfg.json"
        device = QubiCDeviceSpec.from_qubitcfg(qubitcfg_path)

        # Check Q0 (logical qubit 0, hardware Q1)
        q0 = device.qubits[0]
        assert q0.hardware_qubit == "Q1"
        assert 4e9 < q0.drive_frequency_hz < 6e9  # Reasonable qubit frequency
        assert 6e9 < q0.readout_frequency_hz < 8e9  # Reasonable readout frequency
        assert 0 < q0.x90_duration_ns < 100  # Reasonable pulse duration
        assert 0 < q0.readout_duration_ns < 5000  # Reasonable readout duration

        # Check directed CNOT calibration
        cnot = device.directed_cnot_edges[(1, 0)]
        assert cnot.control_hardware == "Q2"
        assert cnot.target_hardware == "Q1"
        assert 0 < cnot.cr_duration_ns < 1000  # Reasonable CR pulse duration
        assert 0 < cnot.target_pulse_duration_ns < 200  # Reasonable target pulse

    def test_framework_methods_with_real_config(self):
        """Verify framework implementation with real config."""
        framework = QubiCFramework()

        assert framework.name == "qubic"
        assert "superconducting_cz" in framework.supported_targets
        assert "superconducting_cnot" in framework.supported_targets
