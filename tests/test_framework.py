from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from coda_qubic.config import QubiCConfig
from coda_qubic.executor_factory import build_executor
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


class FakeGMMManager:
    def __init__(
        self,
        *,
        load_file: str | None = None,
        load_json: str | None = None,
        chanmap_or_chan_cfgs: Any = None,
    ) -> None:
        self.load_file = load_file
        self.load_json = load_json
        self.chanmap_or_chan_cfgs = chanmap_or_chan_cfgs
        self.resolved_chanmap = None

    def _resolve_chanmap(self, chanmap_or_chan_cfgs: Any) -> None:
        self.resolved_chanmap = chanmap_or_chan_cfgs


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
    GMMManager=FakeGMMManager,
    JobManager=FakeJobManager,
    PLInterface=FakePLInterface,
    QChip=FakeQChip,
    SimInterface=FakeSimInterface,
    load_channel_configs=fake_load_channel_configs,
)


class TestQubiCFramework:
    def test_name(self):
        assert QubiCFramework().name == "qubic"

    def test_supported_targets(self):
        targets = QubiCFramework().supported_targets
        assert "cz" in targets
        assert "cnot" in targets


class TestQubiCConfig:
    def test_valid_rpc_config(self, qubic_example_qubitcfg_path: Path):
        config = QubiCConfig(
            target="cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path="/tmp/channel_config.json",
            classifier_path="/tmp/gmm.json",
            rpc_host="qubic.local",
            runner_mode="rpc",
        )
        assert config.target == "cnot"
        assert config.rpc_host == "qubic.local"

    def test_missing_rpc_host_raises(self, qubic_example_qubitcfg_path: Path):
        with pytest.raises(ValueError, match="rpc_host is required"):
            QubiCConfig(
                target="cnot",
                num_qubits=3,
                calibration_path=str(qubic_example_qubitcfg_path),
                channel_config_path="/tmp/channel_config.json",
                classifier_path="/tmp/gmm.json",
                runner_mode="rpc",
            )

    def test_unsupported_target_raises(self, qubic_example_qubitcfg_path: Path):
        with pytest.raises(ValueError):
            QubiCConfig(
                target="trapped_ion",
                num_qubits=3,
                calibration_path=str(qubic_example_qubitcfg_path),
                channel_config_path="/tmp/channel_config.json",
                classifier_path="/tmp/gmm.json",
                rpc_host="qubic.local",
            )

    def test_unknown_runner_mode_raises(self, qubic_example_qubitcfg_path: Path):
        with pytest.raises(ValueError):
            QubiCConfig(
                target="cnot",
                num_qubits=3,
                calibration_path=str(qubic_example_qubitcfg_path),
                channel_config_path="/tmp/channel_config.json",
                classifier_path="/tmp/gmm.json",
                runner_mode="unknown",
            )

    def test_local_mode_without_xsa_commit_raises(
        self, qubic_example_qubitcfg_path: Path
    ):
        with pytest.raises(ValueError, match="xsa_commit is required"):
            QubiCConfig(
                target="cnot",
                num_qubits=3,
                calibration_path=str(qubic_example_qubitcfg_path),
                channel_config_path="/tmp/channel_config.json",
                classifier_path="/tmp/gmm.json",
                runner_mode="local",
            )

    def test_local_mode_with_sim_skips_xsa(self, qubic_example_qubitcfg_path: Path):
        config = QubiCConfig(
            target="cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path="/tmp/channel_config.json",
            classifier_path="/tmp/gmm.json",
            runner_mode="local",
            use_sim=True,
        )
        assert config.use_sim is True

    def test_from_yaml(self, tmp_path: Path):
        yaml_file = tmp_path / "device.yaml"
        yaml_file.write_text(
            "framework: qubic\n"
            "target: cnot\n"
            "num_qubits: 3\n"
            "calibration_path: ./qubitcfg.json\n"
            "channel_config_path: ./channel_config.json\n"
            "classifier_path: ./gmm.pkl\n"
            "runner_mode: local\n"
            "use_sim: true\n"
        )
        config = QubiCConfig.from_yaml(yaml_file)
        assert config.target == "cnot"
        assert config.resolved_calibration_path == tmp_path / "qubitcfg.json"

    def test_from_yaml_strips_framework_field(self, tmp_path: Path):
        yaml_file = tmp_path / "device.yaml"
        yaml_file.write_text(
            "framework: qubic\n"
            "target: cnot\n"
            "num_qubits: 3\n"
            "calibration_path: cal.json\n"
            "channel_config_path: chan.json\n"
            "classifier_path: gmm.pkl\n"
            "runner_mode: local\n"
            "use_sim: true\n"
        )
        config = QubiCConfig.from_yaml(yaml_file)
        assert not hasattr(config, "framework")


class TestBuildExecutor:
    def test_creates_rpc_executor(
        self,
        qubic_example_qubitcfg_path: Path,
        qubic_example_channel_config_path: Path,
        qubic_example_gmm_json_path: Path,
    ):
        config = QubiCConfig(
            target="cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path=str(qubic_example_channel_config_path),
            classifier_path=str(qubic_example_gmm_json_path),
            rpc_host="qubic.local",
            rpc_port=9100,
            runner_mode="rpc",
        )

        executor = build_executor(config, dependencies=FAKE_DEPS)

        assert isinstance(executor, QubiCJobRunner)
        assert executor._job_manager.circuit_runner.host == "qubic.local"
        assert executor._job_manager.circuit_runner.port == 9100
        assert executor._job_manager.channel_configs == {
            "loaded_from": str(qubic_example_channel_config_path)
        }
        assert isinstance(executor._job_manager.gmm_manager, FakeGMMManager)
        assert executor._job_manager.gmm_manager.load_json is not None
        assert executor._job_manager.gmm_manager.load_json.endswith(".json")
        assert executor._job_manager.gmm_manager.resolved_chanmap == {
            "loaded_from": str(qubic_example_channel_config_path)
        }
        assert executor._job_manager.qchip.path == str(qubic_example_qubitcfg_path)

    def test_creates_local_sim_executor(
        self,
        qubic_example_qubitcfg_path: Path,
        qubic_example_channel_config_path: Path,
        qubic_example_gmm_json_path: Path,
    ):
        config = QubiCConfig(
            target="cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path=str(qubic_example_channel_config_path),
            classifier_path=str(qubic_example_gmm_json_path),
            runner_mode="local",
            use_sim=True,
        )

        executor = build_executor(config, dependencies=FAKE_DEPS)

        assert isinstance(executor, QubiCJobRunner)
        assert isinstance(
            executor._job_manager.circuit_runner.interface, FakeSimInterface
        )
        assert isinstance(executor._job_manager.gmm_manager, FakeGMMManager)
        assert executor._job_manager.gmm_manager.load_json is not None
        assert executor._job_manager.gmm_manager.load_json.endswith(".json")
        assert executor._job_manager.gmm_manager.resolved_chanmap == {
            "loaded_from": str(qubic_example_channel_config_path)
        }

    def test_creates_local_pl_executor(
        self,
        qubic_example_qubitcfg_path: Path,
        qubic_example_channel_config_path: Path,
        qubic_example_gmm_json_path: Path,
    ):
        config = QubiCConfig(
            target="cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path=str(qubic_example_channel_config_path),
            classifier_path=str(qubic_example_gmm_json_path),
            runner_mode="local",
            xsa_commit="abc123",
        )

        executor = build_executor(config, dependencies=FAKE_DEPS)

        assert isinstance(executor, QubiCJobRunner)
        assert executor._job_manager.circuit_runner.interface.commit_hash == "abc123"
        assert isinstance(executor._job_manager.gmm_manager, FakeGMMManager)
        assert executor._job_manager.gmm_manager.load_json is not None
        assert executor._job_manager.gmm_manager.load_json.endswith(".json")
        assert executor._job_manager.gmm_manager.resolved_chanmap == {
            "loaded_from": str(qubic_example_channel_config_path)
        }

    def test_uses_pickle_classifier_path_directly(
        self,
        qubic_example_qubitcfg_path: Path,
        qubic_example_channel_config_path: Path,
    ):
        config = QubiCConfig(
            target="cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path=str(qubic_example_channel_config_path),
            classifier_path="/tmp/gmm.pkl",
            runner_mode="local",
            use_sim=True,
        )

        executor = build_executor(config, dependencies=FAKE_DEPS)

        assert executor._job_manager.gmm_manager == "/tmp/gmm.pkl"

    def test_rejects_num_qubit_mismatch(
        self,
        qubic_example_qubitcfg_path: Path,
        qubic_example_channel_config_path: Path,
    ):
        config = QubiCConfig(
            target="cnot",
            num_qubits=4,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path=str(qubic_example_channel_config_path),
            classifier_path="/tmp/gmm.json",
            rpc_host="qubic.local",
            runner_mode="rpc",
        )

        with pytest.raises(Exception, match="does not match QubiC device size 3"):
            build_executor(config, dependencies=FAKE_DEPS)
