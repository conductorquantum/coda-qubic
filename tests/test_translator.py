from __future__ import annotations

from pathlib import Path

import pytest
from self_service.server.ir import GateOp, IRMetadata, NativeGateIR

from coda_qubic.device import QubiCDeviceSpec
from coda_qubic.translator import QubiCCircuitTranslator


@pytest.fixture
def device(qubic_example_qubitcfg_path: Path) -> QubiCDeviceSpec:
    return QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)


def _metadata() -> IRMetadata:
    return IRMetadata(source_hash="sha256:test", compiled_at="2026-03-13T00:00:00Z")


class TestQubiCTranslator:
    def test_translates_native_ir_to_qubic_program(self, device: QubiCDeviceSpec):
        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cz",
            gates=[
                GateOp(gate="rx", qubits=[0], params=[3.141592653589793 / 2]),
                GateOp(gate="ry", qubits=[1], params=[0.3]),
                GateOp(gate="rz", qubits=[2], params=[0.4]),
                GateOp(gate="id", qubits=[1], params=[120.0]),
                GateOp(gate="cz", qubits=[0, 1], params=[]),
            ],
            measurements=[2, 0],
            metadata=_metadata(),
        )

        translated = QubiCCircuitTranslator(device).translate(ir)

        assert translated.program[0] == {"name": "X90", "qubit": ["Q1"]}
        assert {
            "name": "delay",
            "t": 120.0 / 1e9,
            "qubit": ["Q2"],
        } in translated.program
        assert {
            "name": "virtual_z",
            "phase": 0.4,
            "qubit": ["Q3"],
        } in translated.program

        cnot_index = translated.program.index({"name": "CNOT", "qubit": ["Q2", "Q1"]})
        assert translated.program[cnot_index - 2 : cnot_index] == [
            {"name": "Y-90", "qubit": ["Q1"]},
            {"name": "virtual_z", "phase": 3.141592653589793, "qubit": ["Q1"]},
        ]
        assert translated.program[cnot_index + 1 : cnot_index + 3] == [
            {"name": "Y-90", "qubit": ["Q1"]},
            {"name": "virtual_z", "phase": 3.141592653589793, "qubit": ["Q1"]},
        ]

        assert translated.measurement_hardware_order == ["Q3", "Q1"]
        assert translated.program[-2:] == [
            {"name": "read", "qubit": ["Q3"]},
            {"name": "read", "qubit": ["Q1"]},
        ]

    def test_rejects_unsupported_two_qubit_pair(self, device: QubiCDeviceSpec):
        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cz",
            gates=[GateOp(gate="cz", qubits=[0, 2], params=[])],
            measurements=[0, 2],
            metadata=_metadata(),
        )

        with pytest.raises(ValueError, match="no calibrated 2Q edge"):
            QubiCCircuitTranslator(device).translate(ir)

    def test_rejects_mismatched_qubit_count(self, device: QubiCDeviceSpec):
        ir = NativeGateIR(
            num_qubits=2,
            target="superconducting_cz",
            gates=[],
            measurements=[0],
            metadata=_metadata(),
        )

        with pytest.raises(ValueError, match="IR has 2 qubits"):
            QubiCCircuitTranslator(device).translate(ir)

    def test_arbitrary_rx_uses_full_zxzxz_decomposition(self, device: QubiCDeviceSpec):
        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cz",
            gates=[GateOp(gate="rx", qubits=[0], params=[0.3])],
            measurements=[0],
            metadata=_metadata(),
        )

        translated = QubiCCircuitTranslator(device).translate(ir)

        assert translated.program[:-1] == [
            {"name": "virtual_z", "phase": -1.5707963267948966, "qubit": ["Q1"]},
            {"name": "X90", "qubit": ["Q1"]},
            {"name": "virtual_z", "phase": 2.8415926535897933, "qubit": ["Q1"]},
            {"name": "X90", "qubit": ["Q1"]},
            {"name": "virtual_z", "phase": -1.5707963267948966, "qubit": ["Q1"]},
        ]

    def test_negative_half_pi_ry_uses_native_y_minus_90(self, device: QubiCDeviceSpec):
        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cz",
            gates=[GateOp(gate="ry", qubits=[1], params=[-3.141592653589793 / 2])],
            measurements=[1],
            metadata=_metadata(),
        )

        translated = QubiCCircuitTranslator(device).translate(ir)

        assert translated.program == [
            {"name": "Y-90", "qubit": ["Q2"]},
            {"name": "read", "qubit": ["Q2"]},
        ]

    def test_zero_rz_and_zero_id_are_emitted_explicitly(self, device: QubiCDeviceSpec):
        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cz",
            gates=[
                GateOp(gate="rz", qubits=[2], params=[0.0]),
                GateOp(gate="id", qubits=[2], params=[0.0]),
            ],
            measurements=[2],
            metadata=_metadata(),
        )

        translated = QubiCCircuitTranslator(device).translate(ir)

        assert translated.program == [
            {"name": "virtual_z", "phase": 0.0, "qubit": ["Q3"]},
            {"name": "delay", "t": 0.0, "qubit": ["Q3"]},
            {"name": "read", "qubit": ["Q3"]},
        ]

    def test_cz_uses_same_directed_cnot_regardless_of_qubit_order(
        self, device: QubiCDeviceSpec
    ):
        translator = QubiCCircuitTranslator(device)
        ir_forward = NativeGateIR(
            num_qubits=3,
            target="superconducting_cz",
            gates=[GateOp(gate="cz", qubits=[0, 1], params=[])],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        ir_reverse = NativeGateIR(
            num_qubits=3,
            target="superconducting_cz",
            gates=[GateOp(gate="cz", qubits=[1, 0], params=[])],
            measurements=[1, 0],
            metadata=_metadata(),
        )

        translated_forward = translator.translate(ir_forward)
        translated_reverse = translator.translate(ir_reverse)

        cnot = {"name": "CNOT", "qubit": ["Q2", "Q1"]}
        assert cnot in translated_forward.program
        assert cnot in translated_reverse.program

    def test_supports_measurement_subsets_in_requested_order(
        self, device: QubiCDeviceSpec
    ):
        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cz",
            gates=[],
            measurements=[1, 0],
            metadata=_metadata(),
        )

        translated = QubiCCircuitTranslator(device).translate(ir)

        assert translated.measurement_hardware_order == ["Q2", "Q1"]
        assert translated.program == [
            {"name": "read", "qubit": ["Q2"]},
            {"name": "read", "qubit": ["Q1"]},
        ]

    def test_translates_qubic_native_target(self, device: QubiCDeviceSpec):
        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cnot",
            gates=[
                GateOp(gate="x90", qubits=[0], params=[]),
                GateOp(gate="y_minus_90", qubits=[1], params=[]),
                GateOp(gate="virtual_z", qubits=[2], params=[0.4]),
                GateOp(gate="id", qubits=[1], params=[120.0]),
                GateOp(gate="cnot", qubits=[1, 0], params=[]),
            ],
            measurements=[2, 0],
            metadata=_metadata(),
        )

        translated = QubiCCircuitTranslator(device).translate(ir)

        assert translated.program == [
            {"name": "X90", "qubit": ["Q1"]},
            {"name": "Y-90", "qubit": ["Q2"]},
            {"name": "virtual_z", "phase": 0.4, "qubit": ["Q3"]},
            {"name": "delay", "t": 120.0 / 1e9, "qubit": ["Q2"]},
            {"name": "CNOT", "qubit": ["Q2", "Q1"]},
            {"name": "read", "qubit": ["Q3"]},
            {"name": "read", "qubit": ["Q1"]},
        ]
        assert translated.measurement_hardware_order == ["Q3", "Q1"]

    def test_reversed_cnot_uses_h_flip_with_warning(
        self, device: QubiCDeviceSpec, caplog: pytest.LogCaptureFixture
    ):
        """CNOT(0,1) when only CNOT(1,0) exists: should H-flip and log a warning."""
        import math

        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cnot",
            gates=[GateOp(gate="cnot", qubits=[0, 1], params=[])],
            measurements=[0, 1],
            metadata=_metadata(),
        )

        with caplog.at_level("WARNING", logger="coda_qubic.translator"):
            translated = QubiCCircuitTranslator(device).translate(ir)

        assert any("falling back to" in r.message for r in caplog.records)
        assert any("CNOT(0, 1)" in r.message for r in caplog.records)

        h_q1 = [
            {"name": "Y-90", "qubit": ["Q1"]},
            {"name": "virtual_z", "phase": math.pi, "qubit": ["Q1"]},
        ]
        h_q2 = [
            {"name": "Y-90", "qubit": ["Q2"]},
            {"name": "virtual_z", "phase": math.pi, "qubit": ["Q2"]},
        ]
        cnot_hw = {"name": "CNOT", "qubit": ["Q2", "Q1"]}

        expected_gate_program = [*h_q1, *h_q2, cnot_hw, *h_q1, *h_q2]
        assert translated.program[: len(expected_gate_program)] == expected_gate_program

    def test_rejects_cnot_with_no_edge_in_either_direction(
        self, device: QubiCDeviceSpec
    ):
        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cnot",
            gates=[GateOp(gate="cnot", qubits=[0, 2], params=[])],
            measurements=[0, 2],
            metadata=_metadata(),
        )

        with pytest.raises(ValueError, match="no calibrated CNOT edge"):
            QubiCCircuitTranslator(device).translate(ir)

    def test_cloud_compiled_cnot_ir_with_rx_ry_rz(self, device: QubiCDeviceSpec):
        """Cloud compiler produces {rx, ry, rz, cnot} for superconducting_cnot target."""
        import math

        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cnot",
            gates=[
                GateOp(gate="rx", qubits=[0], params=[math.pi / 2]),
                GateOp(gate="ry", qubits=[1], params=[-math.pi / 2]),
                GateOp(gate="rz", qubits=[2], params=[0.4]),
                GateOp(gate="cnot", qubits=[1, 0], params=[]),
            ],
            measurements=[0, 1, 2],
            metadata=_metadata(),
        )

        translated = QubiCCircuitTranslator(device).translate(ir)

        assert translated.program[0] == {"name": "X90", "qubit": ["Q1"]}
        assert {"name": "Y-90", "qubit": ["Q2"]} in translated.program
        assert {
            "name": "virtual_z",
            "phase": 0.4,
            "qubit": ["Q3"],
        } in translated.program
        assert {"name": "CNOT", "qubit": ["Q2", "Q1"]} in translated.program

    def test_rejects_unsupported_target(self, device: QubiCDeviceSpec):
        ir = NativeGateIR(
            num_qubits=3,
            target="trapped_ion",
            gates=[],
            measurements=[0],
            metadata=_metadata(),
        )

        with pytest.raises(
            ValueError,
            match="only supports superconducting_cz and superconducting_cnot",
        ):
            QubiCCircuitTranslator(device).translate(ir)
