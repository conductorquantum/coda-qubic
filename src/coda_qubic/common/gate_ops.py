"""Target-agnostic gate construction helpers and angular constants.

Provides functions that emit the correct :class:`GateOp` sequence for a
given native gate-set target (``"cnot"`` or ``"cz"``), so that experiment
and benchmark modules can build circuits without hard-coding gate choices.
"""

from __future__ import annotations

import math

from coda_node.server.ir import GateOp, NativeGate

__all__ = [
    "HALF_PI",
    "NEG_HALF_PI",
    "PI",
    "delay_op",
    "x90_ops",
    "x180_ops",
]

# ---------------------------------------------------------------------------
# Angular constants (radians)
# ---------------------------------------------------------------------------

HALF_PI: float = math.pi / 2
PI: float = math.pi
NEG_HALF_PI: float = -math.pi / 2

# ---------------------------------------------------------------------------
# Gate operation builders
# ---------------------------------------------------------------------------


def x90_ops(qubit: int, target: str) -> list[GateOp]:
    """Emit gate operations for a π/2 rotation about X.

    For the ``"cnot"`` target the native ``X90`` gate is used directly.
    For other targets (e.g. ``"cz"``) an ``RX(π/2)`` is emitted instead.

    Parameters
    ----------
    qubit:
        Logical qubit index the rotation acts on.
    target:
        Native gate-set identifier (``"cnot"`` or ``"cz"``).
    """
    if target == "cnot":
        return [GateOp(gate=NativeGate.X90, qubits=[qubit], params=[])]
    return [GateOp(gate=NativeGate.RX, qubits=[qubit], params=[HALF_PI])]


def x180_ops(qubit: int, target: str) -> list[GateOp]:
    """Emit gate operations for a full π rotation about X.

    For the ``"cnot"`` target two consecutive ``X90`` pulses are used.
    For other targets a single ``RX(π)`` is emitted.

    Parameters
    ----------
    qubit:
        Logical qubit index the rotation acts on.
    target:
        Native gate-set identifier (``"cnot"`` or ``"cz"``).
    """
    if target == "cnot":
        return [
            GateOp(gate=NativeGate.X90, qubits=[qubit], params=[]),
            GateOp(gate=NativeGate.X90, qubits=[qubit], params=[]),
        ]
    return [GateOp(gate=NativeGate.RX, qubits=[qubit], params=[PI])]


def delay_op(qubit: int, delay_ns: float) -> GateOp:
    """Emit an identity / delay gate with the given duration.

    Parameters
    ----------
    qubit:
        Logical qubit index.
    delay_ns:
        Delay duration in nanoseconds.
    """
    return GateOp(gate=NativeGate.ID, qubits=[qubit], params=[delay_ns])
