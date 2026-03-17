"""Helpers for loading the optional local QubiC stack.

The QubiC integration depends on local vendor checkouts that are not importable
from the default Python environment. Keep the path mutation and imports isolated
here so other codepaths remain unaffected.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class QubiCDependencies:
    CircuitRunner: type[Any]
    CircuitRunnerClient: type[Any]
    FPGAConfig: type[Any]
    JobManager: type[Any]
    PLInterface: type[Any]
    QChip: type[Any]
    SimInterface: type[Any]
    load_channel_configs: Callable[[str], Any]


def ensure_qubic_sys_path(qubic_root: Path | None = None) -> None:
    if qubic_root is None:
        env_root = os.environ.get("QUBIC_ROOT")
        if env_root:
            qubic_root = Path(env_root)
        else:
            return

    candidates = (
        qubic_root / "software",
        qubic_root / "distributed_processor" / "python",
    )
    for candidate in reversed(candidates):
        if candidate.exists():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)


def load_qubic_dependencies(
    qubic_root: Path | None = None,
) -> QubiCDependencies:
    ensure_qubic_sys_path(qubic_root)
    try:
        from distproc.hwconfig import FPGAConfig, load_channel_configs
        from qubic.job_manager import JobManager
        from qubic.rfsoc.pl_interface import PLInterface
        from qubic.rpc_client import CircuitRunnerClient
        from qubic.run import CircuitRunner
        from qubic.sim.sim_interface import SimInterface
        from qubitconfig.qchip import QChip
    except ImportError as exc:
        raise RuntimeError(
            "QubiC dependencies are unavailable. Ensure the local QubiC/distproc "
            "checkouts are present and that the external 'qubitconfig' package is installed."
        ) from exc

    return QubiCDependencies(
        CircuitRunner=CircuitRunner,
        CircuitRunnerClient=CircuitRunnerClient,
        FPGAConfig=FPGAConfig,
        JobManager=JobManager,
        PLInterface=PLInterface,
        QChip=QChip,
        SimInterface=SimInterface,
        load_channel_configs=load_channel_configs,
    )
