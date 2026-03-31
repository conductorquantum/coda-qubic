"""Qubit characterization experiments: T1, T2 Ramsey, and T2 Echo.

Provides circuit construction for standard coherence time measurements
using delay gates (``NativeGate.ID``), and exponential decay fitting
for extracting T1 and T2 times from measurement results.

Circuit conventions:
    - Delay durations are specified in **nanoseconds** (matching the
      ``NativeGate.ID`` parameter convention used by ``coda-node``).
    - For the ``cnot`` target, circuits use native gates (``X90``,
      ``Y_MINUS_90``, ``VIRTUAL_Z``).
    - For the ``cz`` target, circuits use ``RX``/``RY``/``RZ``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from coda_node.server.ir import GateOp, IRMetadata, NativeGate, NativeGateIR
from numpy.typing import NDArray

__all__ = [
    "T1FitResult",
    "T2FitResult",
    "fit_t1_decay",
    "fit_t2_decay",
    "t1_circuits",
    "t2_echo_circuits",
    "t2_ramsey_circuits",
]


def _experiment_metadata() -> IRMetadata:
    return IRMetadata(
        source_hash="sha256:characterization-experiment",
        compiled_at="2026-01-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Gate helpers for target-agnostic circuit construction
# ---------------------------------------------------------------------------


def _x90_ops(qubit: int, target: str) -> list[GateOp]:
    """Single π/2 rotation about X."""
    if target == "cnot":
        return [GateOp(gate=NativeGate.X90, qubits=[qubit], params=[])]
    return [GateOp(gate=NativeGate.RX, qubits=[qubit], params=[math.pi / 2])]


def _x180_ops(qubit: int, target: str) -> list[GateOp]:
    """Full π rotation about X."""
    if target == "cnot":
        return [
            GateOp(gate=NativeGate.X90, qubits=[qubit], params=[]),
            GateOp(gate=NativeGate.X90, qubits=[qubit], params=[]),
        ]
    return [GateOp(gate=NativeGate.RX, qubits=[qubit], params=[math.pi])]


def _delay_op(qubit: int, delay_ns: float) -> GateOp:
    """Identity/delay gate with duration in nanoseconds."""
    return GateOp(gate=NativeGate.ID, qubits=[qubit], params=[delay_ns])


# ---------------------------------------------------------------------------
# T1 (Energy Relaxation) experiment
# ---------------------------------------------------------------------------


def t1_circuits(
    qubit: int,
    num_qubits: int,
    delay_times_ns: list[float],
    target: str = "cnot",
) -> list[tuple[NativeGateIR, float]]:
    """Build T1 experiment circuits with varying delay times.

    Each circuit prepares |1⟩ via an X180 gate, waits for a variable
    delay, then measures.  The excited-state population P(|1⟩) decays
    exponentially with time constant T1.

    Sequence per circuit::

        X180 → delay(t) → measure

    Returns a list of ``(ir, delay_time_ns)`` pairs.
    """
    circuits: list[tuple[NativeGateIR, float]] = []
    for delay_ns in delay_times_ns:
        gates = [
            *_x180_ops(qubit, target),
            _delay_op(qubit, delay_ns),
        ]
        ir = NativeGateIR(
            target=target,
            num_qubits=num_qubits,
            gates=gates,
            measurements=[qubit],
            metadata=_experiment_metadata(),
        )
        circuits.append((ir, delay_ns))
    return circuits


# ---------------------------------------------------------------------------
# T2 Ramsey (Free Induction Decay) experiment
# ---------------------------------------------------------------------------


def t2_ramsey_circuits(
    qubit: int,
    num_qubits: int,
    delay_times_ns: list[float],
    target: str = "cnot",
) -> list[tuple[NativeGateIR, float]]:
    """Build T2 Ramsey (free induction decay) experiment circuits.

    Each circuit creates a superposition via X90, waits, then applies
    a second X90 before measurement.  The survival probability decays
    with time constant T2* (which may include oscillations if there is
    a detuning between the drive and qubit frequencies).

    Sequence per circuit::

        X90 → delay(t) → X90 → measure

    Returns a list of ``(ir, delay_time_ns)`` pairs.
    """
    circuits: list[tuple[NativeGateIR, float]] = []
    for delay_ns in delay_times_ns:
        gates = [
            *_x90_ops(qubit, target),
            _delay_op(qubit, delay_ns),
            *_x90_ops(qubit, target),
        ]
        ir = NativeGateIR(
            target=target,
            num_qubits=num_qubits,
            gates=gates,
            measurements=[qubit],
            metadata=_experiment_metadata(),
        )
        circuits.append((ir, delay_ns))
    return circuits


# ---------------------------------------------------------------------------
# T2 Echo (Hahn Echo) experiment
# ---------------------------------------------------------------------------


def t2_echo_circuits(
    qubit: int,
    num_qubits: int,
    delay_times_ns: list[float],
    target: str = "cnot",
) -> list[tuple[NativeGateIR, float]]:
    """Build T2 Echo (Hahn echo) experiment circuits.

    Each circuit applies X90, waits half the total delay, applies an
    X180 refocusing pulse, waits the other half, then applies X90 and
    measures.  The echo refocuses low-frequency noise, yielding a
    T2_echo time that is typically longer than T2* from a Ramsey
    experiment.

    Sequence per circuit::

        X90 → delay(t/2) → X180 → delay(t/2) → X90 → measure

    Returns a list of ``(ir, delay_time_ns)`` pairs.
    """
    circuits: list[tuple[NativeGateIR, float]] = []
    for delay_ns in delay_times_ns:
        half_delay = delay_ns / 2.0
        gates = [
            *_x90_ops(qubit, target),
            _delay_op(qubit, half_delay),
            *_x180_ops(qubit, target),
            _delay_op(qubit, half_delay),
            *_x90_ops(qubit, target),
        ]
        ir = NativeGateIR(
            target=target,
            num_qubits=num_qubits,
            gates=gates,
            measurements=[qubit],
            metadata=_experiment_metadata(),
        )
        circuits.append((ir, delay_ns))
    return circuits


# ---------------------------------------------------------------------------
# Decay fitting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class T1FitResult:
    """Result of fitting a T1 energy relaxation decay curve."""

    t1_ns: float
    fit_amplitude: float
    fit_offset: float


@dataclass(frozen=True)
class T2FitResult:
    """Result of fitting a T2 dephasing decay curve."""

    t2_ns: float
    fit_amplitude: float
    fit_offset: float
    frequency_hz: float


def fit_t1_decay(
    delay_times_ns: list[float],
    excited_state_probabilities: list[float],
) -> T1FitResult:
    r"""Fit ``f(t) = A \cdot e^{-t/T_1} + B`` to T1 decay data.

    Parameters
    ----------
    delay_times_ns:
        Delay durations in nanoseconds.
    excited_state_probabilities:
        Measured P(|1⟩) at each delay point.

    Returns
    -------
    T1FitResult
        Extracted T1 time and fit parameters.
    """
    from scipy.optimize import curve_fit

    def _model(
        t: NDArray[np.floating], a: float, t1: float, b: float
    ) -> NDArray[np.floating]:
        result: NDArray[np.floating] = a * np.exp(-t / t1) + b
        return result

    times = np.asarray(delay_times_ns, dtype=float)
    probs = np.asarray(excited_state_probabilities, dtype=float)

    a0 = float(np.max(probs) - np.min(probs))
    t1_0 = float(np.max(times) - np.min(times)) / 2.0
    b0 = float(np.min(probs))

    if t1_0 <= 0:
        t1_0 = 1000.0

    popt, _ = curve_fit(
        _model,
        times,
        probs,
        p0=[a0, t1_0, b0],
        bounds=([0, 1e-3, 0], [1, np.inf, 1]),
        maxfev=10000,
    )
    a, t1, b = popt
    return T1FitResult(
        t1_ns=float(t1),
        fit_amplitude=float(a),
        fit_offset=float(b),
    )


def fit_t2_decay(
    delay_times_ns: list[float],
    survival_probabilities: list[float],
    *,
    with_oscillation: bool = False,
) -> T2FitResult:
    r"""Fit a T2 decay curve to experimental data.

    Without oscillation (echo)::

        f(t) = A \cdot e^{-t/T_2} + B

    With oscillation (Ramsey with detuning)::

        f(t) = A \cdot e^{-t/T_2} \cdot \cos(2\pi f t + \varphi) + B

    Parameters
    ----------
    delay_times_ns:
        Total delay durations in nanoseconds.
    survival_probabilities:
        Measured P(|0⟩) at each delay point.
    with_oscillation:
        If ``True``, fit includes a cosine oscillation term (Ramsey
        with detuning).  If ``False``, fit is a pure exponential
        (echo or on-resonance Ramsey).

    Returns
    -------
    T2FitResult
        Extracted T2 time, detuning frequency, and fit parameters.
    """
    from scipy.optimize import curve_fit

    times = np.asarray(delay_times_ns, dtype=float)
    probs = np.asarray(survival_probabilities, dtype=float)

    if not with_oscillation:

        def _model(
            t: NDArray[np.floating], a: float, t2: float, b: float
        ) -> NDArray[np.floating]:
            result: NDArray[np.floating] = a * np.exp(-t / t2) + b
            return result

        a0 = float(np.max(probs) - np.min(probs))
        t2_0 = float(np.max(times) - np.min(times)) / 2.0
        b0 = float(np.min(probs))
        if t2_0 <= 0:
            t2_0 = 1000.0

        popt, _ = curve_fit(
            _model,
            times,
            probs,
            p0=[a0, t2_0, b0],
            bounds=([0, 1e-3, 0], [1, np.inf, 1]),
            maxfev=10000,
        )
        a, t2, b = popt
        return T2FitResult(
            t2_ns=float(t2),
            fit_amplitude=float(a),
            fit_offset=float(b),
            frequency_hz=0.0,
        )

    def _model_osc(
        t: NDArray[np.floating],
        a: float,
        t2: float,
        f: float,
        phi: float,
        b: float,
    ) -> NDArray[np.floating]:
        result: NDArray[np.floating] = (
            a * np.exp(-t / t2) * np.cos(2 * np.pi * f * t + phi) + b
        )
        return result

    a0 = float(np.max(probs) - np.min(probs)) / 2.0
    t2_0 = float(np.max(times) - np.min(times)) / 2.0
    if t2_0 <= 0:
        t2_0 = 1000.0
    f0 = 1e-4
    phi0 = 0.0
    b0 = float(np.mean(probs))

    popt, _ = curve_fit(
        _model_osc,
        times,
        probs,
        p0=[a0, t2_0, f0, phi0, b0],
        bounds=(
            [-1, 1e-3, 0, -2 * np.pi, 0],
            [1, np.inf, np.inf, 2 * np.pi, 1],
        ),
        maxfev=10000,
    )
    a, t2, f, _phi, b = popt
    return T2FitResult(
        t2_ns=float(t2),
        fit_amplitude=float(a),
        fit_offset=float(b),
        frequency_hz=float(f * 1e9),
    )
