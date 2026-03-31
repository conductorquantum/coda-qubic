"""QubiC execution framework for coda-node."""

from coda_qubic.config import QubiCConfig
from coda_qubic.experiments import (
    T1FitResult,
    T2FitResult,
    fit_t1_decay,
    fit_t2_decay,
    t1_circuits,
    t2_echo_circuits,
    t2_ramsey_circuits,
)
from coda_qubic.framework import QubiCFramework

__all__ = [
    "QiskitNoisySimulator",
    "QubiCConfig",
    "QubiCFramework",
    "T1FitResult",
    "T2FitResult",
    "fit_t1_decay",
    "fit_t2_decay",
    "t1_circuits",
    "t2_echo_circuits",
    "t2_ramsey_circuits",
]
__version__ = "0.1.0"


def __getattr__(name: str) -> object:
    if name == "QiskitNoisySimulator":
        from coda_qubic.qiskit_sim import QiskitNoisySimulator

        return QiskitNoisySimulator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
