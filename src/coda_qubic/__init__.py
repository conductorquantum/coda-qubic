"""QubiC execution framework for coda-node."""

from coda_qubic.config import QubiCConfig
from coda_qubic.framework import QubiCFramework

__all__ = ["QubiCConfig", "QubiCFramework", "QiskitNoisySimulator"]  # noqa: F822
__version__ = "0.1.0"


def __getattr__(name: str) -> object:
    if name == "QiskitNoisySimulator":
        from coda_qubic.qiskit_sim import QiskitNoisySimulator

        return QiskitNoisySimulator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
