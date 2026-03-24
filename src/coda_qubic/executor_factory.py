"""Executor factory for ``CODA_EXECUTOR_FACTORY``.

Usage::

    CODA_EXECUTOR_FACTORY=coda_qubic.executor_factory:create_executor \\
    CODA_DEVICE_CONFIG=./site/device.yaml \\
    uv run coda start --token <token>
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from self_service.errors import ExecutorError

from coda_qubic.config import QubiCConfig
from coda_qubic.device import QubiCDeviceSpec
from coda_qubic.runner import QubiCJobRunner
from coda_qubic.support import QubiCDependencies, load_qubic_dependencies

if TYPE_CHECKING:
    from self_service.server.executor import JobExecutor

__all__ = ["create_executor"]


def create_executor(settings: Any) -> JobExecutor:
    """Build a QubiC executor from ``settings.device_config``.

    This is the entry point for ``CODA_EXECUTOR_FACTORY``.  It reads the
    device YAML path from *settings*, validates the configuration, and
    assembles the full QubiC pipeline (device spec, circuit runner, job
    manager).
    """
    device_config_path = getattr(settings, "device_config", "") or ""
    if not device_config_path:
        raise ExecutorError(
            "CODA_DEVICE_CONFIG must be set when using the QubiC executor factory"
        )

    try:
        config = QubiCConfig.from_yaml(device_config_path)
    except FileNotFoundError:
        raise ExecutorError(f"Device config not found: {device_config_path}") from None
    except Exception as exc:
        raise ExecutorError(
            f"Invalid device config {device_config_path!r}: {exc}"
        ) from exc

    return build_executor(config)


def build_executor(
    config: QubiCConfig,
    *,
    dependencies: QubiCDependencies | None = None,
) -> QubiCJobRunner:
    """Assemble a :class:`QubiCJobRunner` from a validated config.

    Separated from :func:`create_executor` so that tests and programmatic
    callers can bypass YAML loading.
    """
    cal_path = config.resolved_calibration_path
    deps = dependencies or load_qubic_dependencies(config.resolved_qubic_root)

    device = QubiCDeviceSpec.from_qubitcfg(cal_path)

    if config.num_qubits != device.num_qubits:
        raise ExecutorError(
            f"Configured num_qubits={config.num_qubits} does not match "
            f"QubiC device size {device.num_qubits}. Update the device config "
            f"to num_qubits={device.num_qubits}."
        )

    circuit_runner = _build_circuit_runner(config, deps)
    qchip = deps.QChip(str(cal_path))
    channel_configs = deps.load_channel_configs(
        str(config.resolved_channel_config_path)
    )
    fpga_config = deps.FPGAConfig()
    gmm_manager = _build_gmm_manager(config, channel_configs, deps)
    job_manager = deps.JobManager(
        fpga_config,
        channel_configs,
        circuit_runner,
        qchip=qchip,
        gmm_manager=gmm_manager,
    )

    return QubiCJobRunner(
        job_manager=job_manager,
        device=device,
        native_gate_set=config.target,
    )


def _build_circuit_runner(config: QubiCConfig, deps: QubiCDependencies) -> Any:
    if config.runner_mode == "rpc":
        return deps.CircuitRunnerClient(config.rpc_host, config.rpc_port)
    if config.use_sim:
        return deps.CircuitRunner(deps.SimInterface())
    return deps.CircuitRunner(deps.PLInterface(commit_hash=config.xsa_commit))


def _build_gmm_manager(
    config: QubiCConfig, channel_configs: Any, deps: QubiCDependencies
) -> Any:
    classifier_path = config.resolved_classifier_path
    if Path(classifier_path).suffix.lower() == ".json":
        return _load_json_gmm_manager(classifier_path, channel_configs, deps)
    return str(classifier_path)


def _load_json_gmm_manager(
    classifier_path: Path, channel_configs: Any, deps: QubiCDependencies
) -> Any:
    raw = json.loads(classifier_path.read_text())
    if "qubits" not in raw:
        return deps.GMMManager(
            load_json=str(classifier_path),
            chanmap_or_chan_cfgs=channel_configs,
        )

    translated = {
        qubit: _translate_placeholder_gmm(qubit_data)
        for qubit, qubit_data in raw["qubits"].items()
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(translated, handle)
        temp_path = handle.name

    try:
        return deps.GMMManager(
            load_json=temp_path,
            chanmap_or_chan_cfgs=channel_configs,
        )
    finally:
        os.unlink(temp_path)


def _translate_placeholder_gmm(qubit_data: dict[str, Any]) -> dict[str, Any]:
    means = np.asarray(qubit_data["means"], dtype=float)
    covariances = np.asarray(qubit_data["covariances"], dtype=float)
    weights = np.asarray(qubit_data["weights"], dtype=float)
    precisions = np.linalg.inv(covariances)
    precisions_cholesky = np.linalg.cholesky(precisions)
    n_states = len(weights)

    return {
        "labels": list(range(n_states)),
        "gmm": {
            "weights_": weights.tolist(),
            "means_": means.tolist(),
            "covariances_": covariances.tolist(),
            "precisions_": precisions.tolist(),
            "precisions_cholesky_": precisions_cholesky.tolist(),
            "covariance_type": "full",
            "n_components": n_states,
            "converged_": True,
            "n_features_in_": int(means.shape[1]),
            "lower_bound_": 0.0,
            "n_iter_": 1,
        },
    }
