from __future__ import annotations

import os
from pathlib import Path

import pytest
from self_service.server.ir import GateOp, IRMetadata, NativeGateIR

from coda_qubic.device import QubiCDeviceSpec
from coda_qubic.support import load_qubic_dependencies
from coda_qubic.translator import QubiCCircuitTranslator

QUBIC_ROOT = Path(os.environ.get("QUBIC_ROOT", ""))
EXAMPLE_QUBITCFG = QUBIC_ROOT / "software" / "examples" / "qubitcfg.json"
EXAMPLE_CHANNEL_CONFIG = QUBIC_ROOT / "software" / "examples" / "channel_config.json"


def _metadata() -> IRMetadata:
    return IRMetadata(source_hash="sha256:test", compiled_at="2026-03-13T00:00:00Z")


def _qubic_modules():
    try:
        load_qubic_dependencies()
        import qubic.toolchain as tc
    except Exception as exc:
        pytest.skip(f"QubiC compile dependencies unavailable: {exc}")
    return tc


@pytest.mark.parametrize(
    ("target", "gates", "measurements"),
    [
        (
            "superconducting_cz",
            [GateOp(gate="rx", qubits=[0], params=[3.141592653589793 / 2])],
            [0],
        ),
        ("superconducting_cz", [GateOp(gate="cz", qubits=[0, 1], params=[])], [0, 1]),
        ("superconducting_cz", [GateOp(gate="cz", qubits=[1, 2], params=[])], [2, 1]),
        (
            "superconducting_cnot",
            [
                GateOp(gate="x90", qubits=[0], params=[]),
                GateOp(gate="virtual_z", qubits=[1], params=[0.125]),
                GateOp(gate="cnot", qubits=[1, 0], params=[]),
            ],
            [1, 0],
        ),
    ],
)
def test_translated_qubic_program_compiles_and_assembles(target, gates, measurements):
    if not EXAMPLE_QUBITCFG.exists() or not EXAMPLE_CHANNEL_CONFIG.exists():
        pytest.skip("local QubiC example configs unavailable")

    tc = _qubic_modules()

    deps = load_qubic_dependencies()
    device = QubiCDeviceSpec.from_qubitcfg(EXAMPLE_QUBITCFG)
    ir = NativeGateIR(
        num_qubits=device.num_qubits,
        target=target,
        gates=gates,
        measurements=measurements,
        metadata=_metadata(),
    )
    translated = QubiCCircuitTranslator(device).translate(ir)

    fpga_config = deps.FPGAConfig()
    qchip = deps.QChip(str(EXAMPLE_QUBITCFG))
    channel_configs = deps.load_channel_configs(str(EXAMPLE_CHANNEL_CONFIG))

    compiled = tc.run_compile_stage(translated.program, fpga_config, qchip)
    assembled = tc.run_assemble_stage(compiled, channel_configs)

    assert compiled is not None
    assert assembled is not None
