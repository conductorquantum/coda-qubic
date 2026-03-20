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

from pathlib import Path
from typing import TYPE_CHECKING, Any

from self_service.errors import ExecutorError
from self_service.frameworks.base import DeviceConfig

from coda_qubic.device import QubiCDeviceSpec
from coda_qubic.runner import QubiCJobRunner
from coda_qubic.support import QubiCDependencies, load_qubic_dependencies

if TYPE_CHECKING:
    from self_service.server.config import Settings
    from self_service.server.executor import JobExecutor

__all__ = ["QubiCFramework"]

_SUPPORTED_TARGETS = frozenset({"superconducting_cz", "superconducting_cnot"})


class QubiCFramework:
    """LBNL QubiC execution framework.

    Parses ``qubitcfg.json`` to derive a ``QubiCDeviceSpec`` (BFS over the
    calibrated connectivity graph), translates IR circuits into QubiC
    gate-level programs, and executes via ``JobManager`` (RPC client or
    local runner).

    Protocol Compliance
    -------------------
    This class implements the ``Framework`` protocol from
    ``self_service.frameworks.base``, which is decorated with
    ``@runtime_checkable``, allowing runtime type checks via ``isinstance``.

    The ``QubiCJobRunner`` returned by ``create_executor()`` implements the
    ``JobExecutor`` protocol from ``self_service.server.executor``, which is
    also decorated with ``@runtime_checkable``, enabling runtime type checks.
    """

    @property
    def name(self) -> str:
        return "qubic"

    @property
    def supported_targets(self) -> frozenset[str]:
        return _SUPPORTED_TARGETS

    def validate_config(self, device_config: DeviceConfig) -> list[str]:
        errors: list[str] = []

        if device_config.target not in _SUPPORTED_TARGETS:
            errors.append(
                f"Target {device_config.target!r} not supported by QubiC framework. "
                f"Supported: {sorted(_SUPPORTED_TARGETS)}"
            )

        cal_path = device_config.resolved_calibration_path
        if cal_path is None:
            errors.append(
                "calibration_path is required for the QubiC framework "
                "(must point to qubitcfg.json)"
            )
        elif not cal_path.exists():
            errors.append(f"Calibration file not found: {cal_path}")

        raw_channel = device_config.get_option("channel_config_path")
        if not raw_channel:
            errors.append("channel_config_path is required (set in device config)")

        raw_classifier = device_config.get_option("classifier_path")
        if not raw_classifier:
            errors.append("classifier_path is required (set in device config)")

        runner_mode = device_config.get_option("runner_mode", "rpc")
        if runner_mode == "rpc":
            if not device_config.get_option("rpc_host"):
                errors.append("rpc_host is required when runner_mode is 'rpc'")
        elif runner_mode == "local":
            use_sim = device_config.get_option("use_sim", False)
            if not use_sim and not device_config.get_option("xsa_commit"):
                errors.append(
                    "xsa_commit is required for local QubiC execution "
                    "unless use_sim is true"
                )
        else:
            errors.append(
                f"Unknown runner_mode {runner_mode!r}. Must be 'rpc' or 'local'."
            )

        return errors

    def create_executor(
        self,
        device_config: DeviceConfig,
        settings: Settings,
        *,
        dependencies: QubiCDependencies | None = None,
    ) -> JobExecutor:
        """Construct a QubiC executor wired to the physical hardware.

        Reads connection parameters from *device_config* options and
        assembles the full QubiC pipeline (device spec, circuit runner,
        job manager).
        """
        cal_path = device_config.resolved_calibration_path
        if cal_path is None:
            raise ExecutorError("calibration_path is required for the QubiC framework")

        deps = dependencies or load_qubic_dependencies(
            _resolve_qubic_root(device_config)
        )

        device = QubiCDeviceSpec.from_qubitcfg(cal_path)

        _validate_device_size(device_config, device)

        circuit_runner = _build_circuit_runner(device_config, deps)
        qchip = deps.QChip(str(cal_path))
        channel_config_path = _resolve_option_path(device_config, "channel_config_path")
        channel_configs = deps.load_channel_configs(str(channel_config_path))
        fpga_config = deps.FPGAConfig()
        classifier_path = _resolve_option_path(device_config, "classifier_path")
        job_manager = deps.JobManager(
            fpga_config,
            channel_configs,
            circuit_runner,
            qchip=qchip,
            gmm_manager=str(classifier_path),
        )

        return QubiCJobRunner(
            job_manager=job_manager,
            device=device,
            native_gate_set=device_config.target,
        )


def _resolve_option_path(device_config: DeviceConfig, key: str) -> Path:
    """Resolve a file-path option relative to the YAML file's directory.

    Uses the same ``_source_dir`` that :pymethod:`DeviceConfig.from_yaml`
    stores, falling back to the current working directory for
    programmatically constructed instances (mirrors
    ``resolved_calibration_path``).
    """
    raw = device_config.get_option(key)
    if raw is None:
        raise ExecutorError(f"{key} is required (set in device config)")
    p = Path(raw)
    if p.is_absolute():
        return p
    base: Path = getattr(device_config, "_source_dir", None) or Path.cwd()
    return base / p


def _resolve_qubic_root(device_config: DeviceConfig) -> Path | None:
    raw = device_config.get_option("qubic_root")
    if raw is None:
        return None
    p = Path(raw)
    if p.is_absolute():
        return p
    base: Path = getattr(device_config, "_source_dir", None) or Path.cwd()
    return base / p


def _validate_device_size(device_config: DeviceConfig, device: QubiCDeviceSpec) -> None:
    allowed_gate_sets = {"superconducting_cz", "superconducting_cnot"}
    if device_config.target not in allowed_gate_sets:
        raise ExecutorError(
            "QubiC framework expects target to be one of "
            f"{sorted(allowed_gate_sets)}, got {device_config.target}"
        )
    if device_config.num_qubits != device.num_qubits:
        raise ExecutorError(
            f"Configured num_qubits={device_config.num_qubits} does not match "
            f"QubiC device size {device.num_qubits}. Update the device config "
            f"to num_qubits={device.num_qubits}."
        )


def _build_circuit_runner(device_config: DeviceConfig, deps: QubiCDependencies) -> Any:
    runner_mode = device_config.get_option("runner_mode", "rpc")
    if runner_mode == "rpc":
        host = device_config.get_option("rpc_host", "localhost")
        port = device_config.get_option("rpc_port", 9734)
        return deps.CircuitRunnerClient(host, port)
    use_sim = device_config.get_option("use_sim", False)
    if use_sim:
        return deps.CircuitRunner(deps.SimInterface())
    xsa_commit = device_config.get_option("xsa_commit")
    return deps.CircuitRunner(deps.PLInterface(commit_hash=xsa_commit))
