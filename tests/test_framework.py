from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from self_service.frameworks.base import DeviceConfig, Framework

from coda_qubic.framework import QubiCFramework
from coda_qubic.runner import QubiCJobRunner
from coda_qubic.support import QubiCDependencies


class FakeCircuitRunnerClient:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port


class FakeCircuitRunner:
    def __init__(self, interface: Any) -> None:
        self.interface = interface


class FakeFPGAConfig:
    pass


class FakeQChip:
    def __init__(self, path: str) -> None:
        self.path = path


class FakePLInterface:
    def __init__(self, commit_hash: str) -> None:
        self.commit_hash = commit_hash


class FakeSimInterface:
    pass


class FakeJobManager:
    def __init__(
        self,
        fpga_config: Any,
        channel_configs: Any,
        circuit_runner: Any,
        qchip: Any = None,
        gmm_manager: Any = None,
    ) -> None:
        self.fpga_config = fpga_config
        self.channel_configs = channel_configs
        self.circuit_runner = circuit_runner
        self.qchip = qchip
        self.gmm_manager = gmm_manager


def fake_load_channel_configs(path: str) -> dict[str, str]:
    return {"loaded_from": path}


FAKE_DEPS = QubiCDependencies(
    CircuitRunner=FakeCircuitRunner,
    CircuitRunnerClient=FakeCircuitRunnerClient,
    FPGAConfig=FakeFPGAConfig,
    JobManager=FakeJobManager,
    PLInterface=FakePLInterface,
    QChip=FakeQChip,
    SimInterface=FakeSimInterface,
    load_channel_configs=fake_load_channel_configs,
)


class TestQubiCFrameworkProtocol:
    def test_satisfies_framework_protocol(self):
        assert isinstance(QubiCFramework(), Framework)

    def test_name(self):
        assert QubiCFramework().name == "qubic"

    def test_supported_targets(self):
        targets = QubiCFramework().supported_targets
        assert "superconducting_cz" in targets
        assert "superconducting_cnot" in targets


class TestValidateConfig:
    def test_valid_rpc_config(self, qubic_example_qubitcfg_path: Path):
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path="/tmp/channel_config.json",
            classifier_path="/tmp/gmm.json",
            rpc_host="qubic.local",
            runner_mode="rpc",
        )

        errors = QubiCFramework().validate_config(config)

        assert errors == []

    def test_missing_calibration_path(self):
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            channel_config_path="/tmp/channel_config.json",
            classifier_path="/tmp/gmm.json",
            rpc_host="qubic.local",
        )

        errors = QubiCFramework().validate_config(config)

        assert any("calibration_path" in e for e in errors)

    def test_missing_classifier_path(self, qubic_example_qubitcfg_path: Path):
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path="/tmp/channel_config.json",
            rpc_host="qubic.local",
        )

        errors = QubiCFramework().validate_config(config)

        assert any("classifier_path" in e for e in errors)

    def test_missing_channel_config_path(self, qubic_example_qubitcfg_path: Path):
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            classifier_path="/tmp/gmm.json",
            rpc_host="qubic.local",
        )

        errors = QubiCFramework().validate_config(config)

        assert any("channel_config_path" in e for e in errors)

    def test_missing_rpc_host(self, qubic_example_qubitcfg_path: Path):
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path="/tmp/channel_config.json",
            classifier_path="/tmp/gmm.json",
            runner_mode="rpc",
        )

        errors = QubiCFramework().validate_config(config)

        assert any("rpc_host" in e for e in errors)

    def test_unsupported_target(self, qubic_example_qubitcfg_path: Path):
        config = DeviceConfig(
            framework="qubic",
            target="trapped_ion",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path="/tmp/channel_config.json",
            classifier_path="/tmp/gmm.json",
            rpc_host="qubic.local",
        )

        errors = QubiCFramework().validate_config(config)

        assert any("not supported" in e for e in errors)

    def test_unknown_runner_mode(self, qubic_example_qubitcfg_path: Path):
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path="/tmp/channel_config.json",
            classifier_path="/tmp/gmm.json",
            runner_mode="unknown",
        )

        errors = QubiCFramework().validate_config(config)

        assert any("runner_mode" in e for e in errors)

    def test_local_mode_without_xsa_commit(self, qubic_example_qubitcfg_path: Path):
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path="/tmp/channel_config.json",
            classifier_path="/tmp/gmm.json",
            runner_mode="local",
        )

        errors = QubiCFramework().validate_config(config)

        assert any("xsa_commit" in e for e in errors)

    def test_local_mode_with_sim_skips_xsa(self, qubic_example_qubitcfg_path: Path):
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path="/tmp/channel_config.json",
            classifier_path="/tmp/gmm.json",
            runner_mode="local",
            use_sim=True,
        )

        errors = QubiCFramework().validate_config(config)

        assert errors == []


class TestCreateExecutor:
    def test_creates_rpc_executor(
        self,
        qubic_example_qubitcfg_path: Path,
        qubic_example_channel_config_path: Path,
    ):
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path=str(qubic_example_channel_config_path),
            classifier_path="/tmp/gmm.json",
            rpc_host="qubic.local",
            rpc_port=9100,
            runner_mode="rpc",
        )
        settings = MagicMock()

        executor = QubiCFramework().create_executor(
            config, settings, dependencies=FAKE_DEPS
        )

        assert isinstance(executor, QubiCJobRunner)
        assert executor._job_manager.circuit_runner.host == "qubic.local"
        assert executor._job_manager.circuit_runner.port == 9100
        assert executor._job_manager.channel_configs == {
            "loaded_from": str(qubic_example_channel_config_path)
        }
        assert executor._job_manager.gmm_manager == "/tmp/gmm.json"
        assert executor._job_manager.qchip.path == str(qubic_example_qubitcfg_path)

    def test_creates_local_sim_executor(
        self,
        qubic_example_qubitcfg_path: Path,
        qubic_example_channel_config_path: Path,
    ):
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path=str(qubic_example_channel_config_path),
            classifier_path="/tmp/gmm.json",
            runner_mode="local",
            use_sim=True,
        )
        settings = MagicMock()

        executor = QubiCFramework().create_executor(
            config, settings, dependencies=FAKE_DEPS
        )

        assert isinstance(executor, QubiCJobRunner)
        assert isinstance(
            executor._job_manager.circuit_runner.interface, FakeSimInterface
        )

    def test_creates_local_pl_executor(
        self,
        qubic_example_qubitcfg_path: Path,
        qubic_example_channel_config_path: Path,
    ):
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path=str(qubic_example_channel_config_path),
            classifier_path="/tmp/gmm.json",
            runner_mode="local",
            xsa_commit="abc123",
        )
        settings = MagicMock()

        executor = QubiCFramework().create_executor(
            config, settings, dependencies=FAKE_DEPS
        )

        assert isinstance(executor, QubiCJobRunner)
        assert executor._job_manager.circuit_runner.interface.commit_hash == "abc123"

    def test_rejects_num_qubit_mismatch(
        self,
        qubic_example_qubitcfg_path: Path,
        qubic_example_channel_config_path: Path,
    ):
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=4,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path=str(qubic_example_channel_config_path),
            classifier_path="/tmp/gmm.json",
            rpc_host="qubic.local",
            runner_mode="rpc",
        )
        settings = MagicMock()

        with pytest.raises(Exception, match="does not match QubiC device size 3"):
            QubiCFramework().create_executor(config, settings, dependencies=FAKE_DEPS)
