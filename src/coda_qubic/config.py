"""QubiC device configuration loaded from YAML.

:class:`QubiCConfig` describes everything needed to wire up a QubiC
executor: IR target, qubit count, calibration/channel/classifier file
paths, and runner mode (RPC, local hardware, or simulator).

All file paths are resolved relative to the YAML file's directory when
loaded via :meth:`QubiCConfig.from_yaml`.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, PrivateAttr, model_validator

__all__ = ["QubiCConfig", "RunnerMode"]

_SUPPORTED_TARGETS = frozenset({"superconducting_cz", "superconducting_cnot"})


class RunnerMode(StrEnum):
    RPC = "rpc"
    LOCAL = "local"


class QubiCConfig(BaseModel):
    """User-supplied QubiC device configuration.

    Example YAML::

        target: superconducting_cnot
        num_qubits: 3
        calibration_path: ./qubitcfg.json
        channel_config_path: ./channel_config.json
        classifier_path: ./gmm_classifier.json
        runner_mode: rpc
        rpc_host: 192.168.1.120
        rpc_port: 9095
    """

    target: Literal["superconducting_cz", "superconducting_cnot"]
    num_qubits: int = Field(ge=1, le=50)
    calibration_path: str
    channel_config_path: str
    classifier_path: str

    runner_mode: RunnerMode = RunnerMode.RPC
    rpc_host: str = ""
    rpc_port: int = 9095
    use_sim: bool = False
    xsa_commit: str = ""
    qubic_root: str = ""

    _source_dir: Path | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def check_runner_requirements(self) -> QubiCConfig:
        if self.runner_mode == RunnerMode.RPC and not self.rpc_host:
            raise ValueError("rpc_host is required when runner_mode is 'rpc'")
        if (
            self.runner_mode == RunnerMode.LOCAL
            and not self.use_sim
            and not self.xsa_commit
        ):
            raise ValueError(
                "xsa_commit is required for local QubiC execution "
                "unless use_sim is true"
            )
        return self

    def resolve_path(self, raw: str) -> Path:
        """Resolve a path relative to the YAML file's directory."""
        p = Path(raw)
        if p.is_absolute():
            return p
        return (self._source_dir or Path.cwd()) / p

    @property
    def resolved_calibration_path(self) -> Path:
        return self.resolve_path(self.calibration_path)

    @property
    def resolved_channel_config_path(self) -> Path:
        return self.resolve_path(self.channel_config_path)

    @property
    def resolved_classifier_path(self) -> Path:
        return self.resolve_path(self.classifier_path)

    @property
    def resolved_qubic_root(self) -> Path | None:
        if not self.qubic_root:
            return None
        return self.resolve_path(self.qubic_root)

    @classmethod
    def from_yaml(cls, path: str | Path) -> QubiCConfig:
        """Load and validate a QubiC device configuration from YAML.

        Relative paths inside the config are resolved against *path*'s
        parent directory.

        Raises:
            FileNotFoundError: If *path* does not exist.
            ValueError: If the file does not contain a YAML mapping.
            pydantic.ValidationError: If the content fails schema validation.
        """
        file_path = Path(path).resolve()
        raw = yaml.safe_load(file_path.read_text())
        if not isinstance(raw, dict):
            raise ValueError(
                f"{file_path}: expected a YAML mapping, got {type(raw).__name__}"
            )

        raw.pop("framework", None)

        config = cls.model_validate(raw)
        config._source_dir = file_path.parent
        return config
