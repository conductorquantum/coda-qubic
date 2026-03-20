"""QubiC framework for LBNL QubiC-based quantum hardware.

Translates :class:`NativeGateIR` circuits into QubiC gate-level
instructions and executes them via the QubiC stack (RPC or local).

QubiC supports two IR targets:

- ``superconducting_cz`` -- generic CZ-based IR, lowered via ZXZXZ
  decomposition and H-CNOT-H CZ synthesis.
- ``superconducting_cnot`` -- native QubiC gates (x90, y_minus_90,
  virtual_z, cnot) passed through directly.
"""

from __future__ import annotations

from coda_qubic.config import QubiCConfig
from coda_qubic.executor_factory import build_executor
from coda_qubic.runner import QubiCJobRunner
from coda_qubic.support import QubiCDependencies

__all__ = ["QubiCFramework"]

_SUPPORTED_TARGETS = frozenset({"superconducting_cz", "superconducting_cnot"})


class QubiCFramework:
    """LBNL QubiC execution framework.

    Parses ``qubitcfg.json`` to derive a ``QubiCDeviceSpec`` (BFS over the
    calibrated connectivity graph), translates IR circuits into QubiC
    gate-level programs, and executes via ``JobManager`` (RPC client or
    local runner).

    The ``QubiCJobRunner`` returned by ``create_executor()`` implements the
    ``JobExecutor`` protocol from ``self_service.server.executor``, which is
    decorated with ``@runtime_checkable``, enabling runtime type checks.
    """

    @property
    def name(self) -> str:
        return "qubic"

    @property
    def supported_targets(self) -> frozenset[str]:
        return _SUPPORTED_TARGETS

    def create_executor(
        self,
        config: QubiCConfig,
        *,
        dependencies: QubiCDependencies | None = None,
    ) -> QubiCJobRunner:
        """Construct a QubiC executor wired to the physical hardware.

        Reads connection parameters from *config* and assembles the full
        QubiC pipeline (device spec, circuit runner, job manager).
        """
        return build_executor(config, dependencies=dependencies)
