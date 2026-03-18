"""Randomized benchmarking utilities for QubiC-based QPUs.

Provides the single-qubit Clifford group (24 elements) decomposed into
QubiC-native gates, RB sequence generation, IR circuit construction,
and decay-curve fitting.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from self_service.server.ir import GateOp, IRMetadata, NativeGate, NativeGateIR

_SQRT2_INV = 1.0 / math.sqrt(2.0)
_HP = math.pi / 2
_PI = math.pi
_NHP = -math.pi / 2

# ---------------------------------------------------------------------------
# Native gate matrices (2x2 unitary)
# ---------------------------------------------------------------------------

_I2 = np.eye(2, dtype=complex)

_X90_MAT: NDArray[np.complexfloating] = np.asarray(
    [[_SQRT2_INV, -1j * _SQRT2_INV], [-1j * _SQRT2_INV, _SQRT2_INV]],
    dtype=complex,
)

_Y_MINUS_90_MAT: NDArray[np.complexfloating] = np.asarray(
    [[_SQRT2_INV, _SQRT2_INV], [-_SQRT2_INV, _SQRT2_INV]],
    dtype=complex,
)


def _vz_mat(phase: float) -> NDArray[np.complexfloating]:
    return np.array([[1, 0], [0, np.exp(1j * phase)]], dtype=complex)


# ---------------------------------------------------------------------------
# Single-qubit Clifford group (24 elements)
# ---------------------------------------------------------------------------

# Each Clifford is a list of (gate_name, params) in time order.
# The 24 elements are organized by the Bloch-sphere axis that +Z maps to
# (6 faces), each with 4 follow-up Z rotations (0, pi/2, pi, -pi/2).

_NativeOp = tuple[str, list[float]]

CLIFFORD_1Q_DECOMPOSITIONS: list[list[_NativeOp]] = [
    # --- Face I: +Z stays at +Z ---
    [],                                                                     # 0:  I
    [("virtual_z", [_HP])],                                                 # 1:  Z90
    [("virtual_z", [_PI])],                                                 # 2:  Z180
    [("virtual_z", [_NHP])],                                                # 3:  Z-90
    # --- Face X90: +Z → -Y ---
    [("x90", [])],                                                          # 4:  X90
    [("x90", []), ("virtual_z", [_HP])],                                    # 5:  X90·Z90
    [("x90", []), ("virtual_z", [_PI])],                                    # 6:  X90·Z180
    [("x90", []), ("virtual_z", [_NHP])],                                   # 7:  X90·Z-90
    # --- Face X180: +Z → -Z ---
    [("x90", []), ("x90", [])],                                             # 8:  X180
    [("x90", []), ("x90", []), ("virtual_z", [_HP])],                       # 9:  X180·Z90
    [("x90", []), ("x90", []), ("virtual_z", [_PI])],                       # 10: X180·Z180
    [("x90", []), ("x90", []), ("virtual_z", [_NHP])],                      # 11: X180·Z-90
    # --- Face X-90: +Z → +Y ---
    [("virtual_z", [_PI]), ("x90", []), ("virtual_z", [_PI])],              # 12: X-90
    [("virtual_z", [_PI]), ("x90", []), ("virtual_z", [_NHP])],             # 13: X-90·Z90
    [("virtual_z", [_PI]), ("x90", [])],                                    # 14: X-90·Z180
    [("virtual_z", [_PI]), ("x90", []), ("virtual_z", [_HP])],              # 15: X-90·Z-90
    # --- Face Y-90: +Z → -X ---
    [("y_minus_90", [])],                                                   # 16: Y-90
    [("y_minus_90", []), ("virtual_z", [_HP])],                             # 17: Y-90·Z90
    [("y_minus_90", []), ("virtual_z", [_PI])],                             # 18: Y-90·Z180
    [("y_minus_90", []), ("virtual_z", [_NHP])],                            # 19: Y-90·Z-90
    # --- Face Y90: +Z → +X ---
    [("virtual_z", [_NHP]), ("x90", []), ("virtual_z", [_HP])],             # 20: Y90
    [("virtual_z", [_NHP]), ("x90", []), ("virtual_z", [_PI])],             # 21: Y90·Z90
    [("virtual_z", [_NHP]), ("x90", []), ("virtual_z", [_NHP])],            # 22: Y90·Z180
    [("virtual_z", [_NHP]), ("x90", [])],                                   # 23: Y90·Z-90
]


def _gate_matrix(name: str, params: list[float]) -> NDArray[np.complexfloating]:
    if name == "x90":
        return _X90_MAT
    if name == "y_minus_90":
        return _Y_MINUS_90_MAT
    if name == "virtual_z":
        return _vz_mat(params[0])
    raise ValueError(f"Unknown native gate: {name}")


def _sequence_matrix(ops: list[_NativeOp]) -> NDArray[np.complexfloating]:
    """Compute the unitary for a time-ordered gate sequence."""
    mat = _I2.copy()
    for name, params in ops:
        mat = _gate_matrix(name, params) @ mat
    return mat


def _matrices_equal_up_to_phase(
    a: NDArray[np.complexfloating],
    b: NDArray[np.complexfloating],
    tol: float = 1e-9,
) -> bool:
    """Check if two 2x2 unitaries are equal up to a global phase."""
    for i in range(2):
        for j in range(2):
            if abs(a[i, j]) > tol:
                phase = b[i, j] / a[i, j]
                return bool(np.allclose(a * phase, b, atol=tol))
    return bool(np.allclose(a, b, atol=tol))


CLIFFORD_1Q_MATRICES: list[NDArray[np.complexfloating]] = [
    _sequence_matrix(decomp) for decomp in CLIFFORD_1Q_DECOMPOSITIONS
]

_INVERSE_TABLE: list[int] = []
_COMPOSE_TABLE: list[list[int]] = []


def _build_tables() -> None:
    n = len(CLIFFORD_1Q_MATRICES)
    for i in range(n):
        mat_inv = CLIFFORD_1Q_MATRICES[i].conj().T
        for j in range(n):
            if _matrices_equal_up_to_phase(CLIFFORD_1Q_MATRICES[j], mat_inv):
                _INVERSE_TABLE.append(j)
                break
        else:
            raise RuntimeError(f"No inverse found for Clifford {i}")

    for i in range(n):
        row: list[int] = []
        for j in range(n):
            composed = CLIFFORD_1Q_MATRICES[j] @ CLIFFORD_1Q_MATRICES[i]
            for k in range(n):
                if _matrices_equal_up_to_phase(CLIFFORD_1Q_MATRICES[k], composed):
                    row.append(k)
                    break
            else:
                raise RuntimeError(f"No match for composition C{j}·C{i}")
        _COMPOSE_TABLE.append(row)


_build_tables()


# ---------------------------------------------------------------------------
# Clifford algebra helpers
# ---------------------------------------------------------------------------


def clifford_1q_inverse(index: int) -> int:
    """Return the Clifford index of the inverse of ``C[index]``."""
    return _INVERSE_TABLE[index]


def compose_cliffords_1q(a: int, b: int) -> int:
    """Return the index *k* such that ``C[k] = C[b] @ C[a]``.

    ``a`` is applied first (closer to |0⟩), ``b`` second.
    """
    return _COMPOSE_TABLE[a][b]


# ---------------------------------------------------------------------------
# 1-qubit RB sequence generation
# ---------------------------------------------------------------------------


def generate_rb_sequence_1q(
    length: int,
    rng: random.Random | None = None,
) -> list[int]:
    """Generate a 1Q RB Clifford sequence of *length* plus a recovery gate.

    Returns ``length + 1`` Clifford indices.  The first *length* are random;
    the last is the recovery Clifford that returns the qubit to |0⟩.
    """
    if rng is None:
        rng = random.Random()

    indices = [rng.randrange(24) for _ in range(length)]
    composite = 0
    for idx in indices:
        composite = compose_cliffords_1q(composite, idx)
    indices.append(clifford_1q_inverse(composite))
    return indices


def rb_ir_circuit_1q(
    clifford_indices: list[int],
    qubit: int,
    num_qubits: int,
    target: str = "superconducting_cnot",
) -> NativeGateIR:
    """Build a ``NativeGateIR`` circuit from a sequence of 1Q Clifford indices."""
    gates: list[GateOp] = []
    for idx in clifford_indices:
        for gate_name, params in CLIFFORD_1Q_DECOMPOSITIONS[idx]:
            gates.append(GateOp(gate=NativeGate(gate_name), qubits=[qubit], params=params))

    return NativeGateIR(
        target=target,
        num_qubits=num_qubits,
        gates=gates,
        measurements=[qubit],
        metadata=IRMetadata(
            source_hash="sha256:rb-circuit",
            compiled_at="2026-01-01T00:00:00Z",
        ),
    )


# ---------------------------------------------------------------------------
# RB decay fitting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RBFitResult:
    """Result of fitting a randomized benchmarking decay curve."""

    depolarizing_parameter: float
    average_gate_fidelity: float
    fit_amplitude: float
    fit_offset: float


def fit_rb_decay(
    sequence_lengths: list[int],
    survival_probabilities: list[float],
) -> RBFitResult:
    """Fit ``f(m) = A · p^m + B`` to RB survival probabilities.

    The average gate fidelity for single-qubit gates is ``(1 + p) / 2``.
    """
    from scipy.optimize import curve_fit  # type: ignore[import-untyped]

    def _model(
        m: NDArray[np.floating], a: float, p: float, b: float
    ) -> NDArray[np.floating]:
        result: NDArray[np.floating] = a * p**m + b
        return result

    lengths_arr = np.asarray(sequence_lengths, dtype=float)
    probs_arr = np.asarray(survival_probabilities, dtype=float)

    popt, _ = curve_fit(
        _model,
        lengths_arr,
        probs_arr,
        p0=[0.5, 0.99, 0.5],
        bounds=([0, 0, 0], [1, 1, 1]),
        maxfev=10000,
    )
    a, p, b = popt
    return RBFitResult(
        depolarizing_parameter=float(p),
        average_gate_fidelity=(1.0 + float(p)) / 2.0,
        fit_amplitude=float(a),
        fit_offset=float(b),
    )


# ---------------------------------------------------------------------------
# 2-qubit characterisation circuits
# ---------------------------------------------------------------------------


def _rb_metadata() -> IRMetadata:
    return IRMetadata(
        source_hash="sha256:benchmark-circuit",
        compiled_at="2026-01-01T00:00:00Z",
    )


def cnot_truth_table_circuits(
    ctrl: int,
    tgt: int,
    num_qubits: int,
    target: str = "superconducting_cnot",
) -> list[tuple[NativeGateIR, str]]:
    """Build 4 CNOT truth-table circuits.

    Returns ``[(ir, expected_bitstring), ...]`` for inputs |00⟩, |10⟩,
    |01⟩, |11⟩.  The expected bitstrings assume standard CNOT action.
    """
    _x90 = NativeGate.X90
    _cnot = NativeGate.CNOT

    cases: list[tuple[list[GateOp], str]] = [
        ([], "00"),
        ([GateOp(gate=_x90, qubits=[ctrl], params=[]),
          GateOp(gate=_x90, qubits=[ctrl], params=[])], "11"),
        ([GateOp(gate=_x90, qubits=[tgt], params=[]),
          GateOp(gate=_x90, qubits=[tgt], params=[])], "01"),
        ([GateOp(gate=_x90, qubits=[ctrl], params=[]),
          GateOp(gate=_x90, qubits=[ctrl], params=[]),
          GateOp(gate=_x90, qubits=[tgt], params=[]),
          GateOp(gate=_x90, qubits=[tgt], params=[])], "10"),
    ]

    circuits: list[tuple[NativeGateIR, str]] = []
    for prep_gates, expected in cases:
        gates = [*prep_gates, GateOp(gate=_cnot, qubits=[ctrl, tgt], params=[])]
        ir = NativeGateIR(
            target=target,
            num_qubits=num_qubits,
            gates=gates,
            measurements=[ctrl, tgt],
            metadata=_rb_metadata(),
        )
        circuits.append((ir, expected))
    return circuits


def bell_state_circuit(
    ctrl: int,
    tgt: int,
    num_qubits: int,
    target: str = "superconducting_cnot",
) -> NativeGateIR:
    """Build a Bell-state preparation circuit (|Φ+⟩ = (|00⟩+|11⟩)/√2).

    Applies H on the control qubit then CNOT.  H is decomposed as
    Y-90 followed by virtual_z(π).
    """
    return NativeGateIR(
        target=target,
        num_qubits=num_qubits,
        gates=[
            GateOp(gate=NativeGate.Y_MINUS_90, qubits=[ctrl], params=[]),
            GateOp(gate=NativeGate.VIRTUAL_Z, qubits=[ctrl], params=[math.pi]),
            GateOp(gate=NativeGate.CNOT, qubits=[ctrl, tgt], params=[]),
        ],
        measurements=[ctrl, tgt],
        metadata=_rb_metadata(),
    )


def cnot_average_gate_fidelity(
    truth_table_counts: list[dict[str, int]],
    expected_bitstrings: list[str],
) -> float:
    """Compute average gate fidelity from CNOT truth-table counts.

    ``truth_table_counts[i]`` is the count dict for the *i*-th truth-table
    circuit, and ``expected_bitstrings[i]`` is the ideal outcome.

    Returns a fidelity in [0, 1].
    """
    fidelities: list[float] = []
    for counts, expected in zip(truth_table_counts, expected_bitstrings, strict=True):
        total = sum(counts.values())
        correct = counts.get(expected, 0)
        fidelities.append(correct / total if total > 0 else 0.0)
    return sum(fidelities) / len(fidelities)
