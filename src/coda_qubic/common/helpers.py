"""Experiment metadata, fit-result protocol, and shared curve fitting.

Provides a metadata factory for tagging experiment circuits, a
:class:`~typing.Protocol` that all fit-result dataclasses satisfy, and a
reusable exponential-decay fitter used by both the characterization and
benchmarking modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
from coda_node.server.ir import IRMetadata
from numpy.typing import NDArray

__all__ = [
    "ExponentialDecayFit",
    "FitResult",
    "experiment_metadata",
    "fit_exponential_decay",
]

# ---------------------------------------------------------------------------
# Experiment metadata
# ---------------------------------------------------------------------------


def experiment_metadata(label: str) -> IRMetadata:
    """Create standard :class:`IRMetadata` for experiment circuits.

    Parameters
    ----------
    label:
        Descriptive tag embedded in the ``source_hash`` field
        (e.g. ``"characterization-experiment"``).

    Returns
    -------
    IRMetadata
        Metadata instance with ``source_hash="sha256:{label}"`` and a
        fixed ``compiled_at`` timestamp.
    """
    return IRMetadata(
        source_hash=f"sha256:{label}",
        compiled_at="2026-01-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Fit-result protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class FitResult(Protocol):
    """Structural interface shared by all curve-fitting result types.

    Every experiment fit result (:class:`~coda_qubic.experiments.T1FitResult`,
    :class:`~coda_qubic.experiments.T2FitResult`,
    :class:`~coda_qubic.benchmarks.RBFitResult`) exposes at least these two
    fields, enabling generic post-processing or plotting code to operate on
    any fit result without knowing the concrete type.
    """

    @property
    def fit_amplitude(self) -> float: ...

    @property
    def fit_offset(self) -> float: ...


# ---------------------------------------------------------------------------
# Shared exponential-decay fitter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExponentialDecayFit:
    r"""Result of fitting :math:`f(x) = A \cdot e^{-x/\tau} + B`.

    Attributes
    ----------
    tau:
        Decay time constant in the same units as the input *x* values.
    fit_amplitude:
        Fitted amplitude *A*.
    fit_offset:
        Fitted baseline offset *B*.
    """

    tau: float
    fit_amplitude: float
    fit_offset: float


def fit_exponential_decay(
    x_values: list[float],
    y_values: list[float],
) -> ExponentialDecayFit:
    r"""Fit :math:`f(x) = A \cdot e^{-x/\tau} + B` to measured data.

    Uses :func:`scipy.optimize.curve_fit` with bounded parameters
    (``A ∈ [0, 1]``, ``τ > 0``, ``B ∈ [0, 1]``) to robustly extract the
    decay constant, amplitude, and baseline.

    Parameters
    ----------
    x_values:
        Independent variable (e.g. delay times in ns).
    y_values:
        Dependent variable (e.g. survival probability), expected in [0, 1].

    Returns
    -------
    ExponentialDecayFit
        Extracted decay constant *τ*, amplitude *A*, and offset *B*.

    Raises
    ------
    RuntimeError
        If the least-squares fit does not converge.
    """
    from scipy.optimize import curve_fit  # type: ignore[import-untyped]

    def _model(
        x: NDArray[np.floating], a: float, tau: float, b: float
    ) -> NDArray[np.floating]:
        result: NDArray[np.floating] = a * np.exp(-x / tau) + b
        return result

    xs = np.asarray(x_values, dtype=float)
    ys = np.asarray(y_values, dtype=float)

    a0 = float(np.max(ys) - np.min(ys))
    tau0 = float(np.max(xs) - np.min(xs)) / 2.0
    b0 = float(np.min(ys))

    if tau0 <= 0:
        tau0 = 1000.0

    popt, _ = curve_fit(
        _model,
        xs,
        ys,
        p0=[a0, tau0, b0],
        bounds=([0, 1e-3, 0], [1, np.inf, 1]),
        maxfev=10000,
    )
    a, tau, b = popt
    return ExponentialDecayFit(
        tau=float(tau),
        fit_amplitude=float(a),
        fit_offset=float(b),
    )
