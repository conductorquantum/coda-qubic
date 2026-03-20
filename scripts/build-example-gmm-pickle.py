#!/usr/bin/env python3
"""Regenerate ``examples/gmm_classifier_sim.pkl`` for ``device_sim.yaml``.

Requires the QubiC stack (run ``./scripts/install-qubic-stack.sh`` first).

Bootstraps an empty ``GMMManager`` (channel map only), runs the pulse simulator
for |000⟩ and |111⟩ with ``fit_gmm=True`` so readout models match simulator IQ,
then forces float labels for QubiC's NaN handling in ``predict``.
"""

from __future__ import annotations

import pickle
from contextlib import chdir
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
from distproc.hwconfig import load_channel_configs
from qubic.state_disc import GMMManager
from self_service.frameworks.base import DeviceConfig
from self_service.server.ir import GateOp, IRMetadata, NativeGateIR

from coda_qubic.framework import QubiCFramework

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
OUT = EXAMPLES / "gmm_classifier_sim.pkl"


def _metadata() -> IRMetadata:
    return IRMetadata(source_hash="gmm-build", compiled_at="2026-03-19T00:00:00Z")


def _x(qubit: int) -> list[GateOp]:
    return [
        GateOp(gate="x90", qubits=[qubit], params=[]),
        GateOp(gate="x90", qubits=[qubit], params=[]),
    ]


def main() -> None:
    with chdir(EXAMPLES):
        channel_configs = load_channel_configs(str(EXAMPLES / "channel_config.json"))
        bootstrap = GMMManager(chanmap_or_chan_cfgs=channel_configs)
        with OUT.open("wb") as f:
            pickle.dump(bootstrap, f)

        config = DeviceConfig.from_yaml(str(EXAMPLES / "device_sim.yaml"))
        framework = QubiCFramework()
        executor = framework.create_executor(config, MagicMock())
        jm = executor._job_manager
        translator = executor._translator

        def run_fit(ir: NativeGateIR, shots: int) -> None:
            translated = translator.translate(ir)
            jm.build_and_run_circuits(
                [translated.program],
                shots,
                ["counts"],
                fit_gmm=True,
                reads_per_shot=1,
            )

        ir0 = NativeGateIR(
            num_qubits=3,
            target="superconducting_cnot",
            gates=[],
            measurements=[0, 1, 2],
            metadata=_metadata(),
        )
        ir1 = NativeGateIR(
            num_qubits=3,
            target="superconducting_cnot",
            gates=[*_x(0), *_x(1), *_x(2)],
            measurements=[0, 1, 2],
            metadata=_metadata(),
        )
        run_fit(ir0, 1500)
        run_fit(ir1, 1500)

        gmm = jm.gmm_manager
        for disc in gmm.gmm_dict.values():
            disc.labels = np.asarray(disc.labels, dtype=np.float64)

        with OUT.open("wb") as f:
            pickle.dump(gmm, f)
        print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
