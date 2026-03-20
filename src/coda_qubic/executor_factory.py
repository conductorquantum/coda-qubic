"""Executor factory for ``CODA_EXECUTOR_FACTORY``.

Usage::

    CODA_EXECUTOR_FACTORY=coda_qubic.executor_factory:create_executor \\
    CODA_DEVICE_CONFIG=./site/device.yaml \\
    uv run coda start --token <token>
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
        raise ExecutorError(
            f"Device config not found: {device_config_path}"
        ) from None
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
    job_manager = deps.JobManager(
        fpga_config,
        channel_configs,
        circuit_runner,
        qchip=qchip,
        gmm_manager=str(config.resolved_classifier_path),
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
