"""Tests for error handling and edge cases to improve coverage."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from self_service.errors import ExecutorError
from self_service.frameworks.base import DeviceConfig
from self_service.server.ir import GateOp, IRMetadata, NativeGateIR

from coda_qubic.device import QubiCDeviceSpec
from coda_qubic.framework import QubiCFramework
from coda_qubic.runner import QubiCJobRunner, _coerce_count_value, _normalize_counts


class TestRunnerErrorHandling:
    """Test error paths in runner.py."""

    def test_translation_error_raises_executor_error(
        self, qubic_example_qubitcfg_path: Path
    ):
        """Test translation failure handling."""
        device = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        job_manager = MagicMock()
        runner = QubiCJobRunner(job_manager, device)

        # Create IR with unsupported target
        ir = NativeGateIR(
            num_qubits=3,
            target="trapped_ion",  # Unsupported target
            gates=[],
            measurements=[0],
            metadata=IRMetadata(source_hash="test", compiled_at="2026-03-16T00:00:00Z"),
        )

        with pytest.raises(ExecutorError, match="QubiC translation failed"):
            asyncio.run(runner.run(ir, shots=100))

    def test_execution_error_raises_executor_error(
        self, qubic_example_qubitcfg_path: Path
    ):
        """Test execution failure handling."""
        device = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        job_manager = MagicMock()
        job_manager.collect_counts.side_effect = RuntimeError("Hardware failure")
        runner = QubiCJobRunner(job_manager, device)

        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cnot",
            gates=[GateOp(gate="x90", qubits=[0], params=[])],
            measurements=[0],
            metadata=IRMetadata(source_hash="test", compiled_at="2026-03-16T00:00:00Z"),
        )

        with pytest.raises(ExecutorError, match="QubiC execution failed"):
            asyncio.run(runner.run(ir, shots=100))

    def test_wrong_number_of_results_raises_executor_error(
        self, qubic_example_qubitcfg_path: Path
    ):
        """Test handling of unexpected number of results."""
        device = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        job_manager = MagicMock()
        job_manager.collect_counts.return_value = [
            MagicMock(),
            MagicMock(),
        ]  # Two results instead of one
        runner = QubiCJobRunner(job_manager, device)

        ir = NativeGateIR(
            num_qubits=3,
            target="superconducting_cnot",
            gates=[GateOp(gate="x90", qubits=[0], params=[])],
            measurements=[0],
            metadata=IRMetadata(source_hash="test", compiled_at="2026-03-16T00:00:00Z"),
        )

        with pytest.raises(ExecutorError, match="Expected one QubiC result, got 2"):
            asyncio.run(runner.run(ir, shots=100))

    def test_normalize_counts_with_mismatched_qubits_raises_error(self):
        """Test count normalization with mismatched qubit sets."""
        circuit_counts = MagicMock()
        circuit_counts.qubits = ["Q1", "Q2"]
        circuit_counts.count_dict = OrderedDict({(0, 0): np.array([5])})

        translated = MagicMock()
        translated.measurement_hardware_order = ["Q1", "Q3"]  # Different qubits

        with pytest.raises(ExecutorError, match="QubiC returned qubits"):
            _normalize_counts(circuit_counts, translated)

    def test_coerce_count_value_with_list_of_multiple_reads(self):
        """Test count coercion with multiple readout buckets."""
        with pytest.raises(ExecutorError, match="Expected a single readout per shot"):
            _coerce_count_value([5, 3])  # Multiple reads

    def test_coerce_count_value_with_numpy_array_multiple_reads(self):
        """Test count coercion with numpy array of multiple reads."""
        with pytest.raises(ExecutorError, match="Expected a single readout per shot"):
            _coerce_count_value(np.array([5, 3, 2]))  # Multiple reads

    def test_coerce_count_value_with_single_element_list(self):
        """Test count coercion with single-element list."""
        assert _coerce_count_value([10]) == 10

    def test_coerce_count_value_with_single_element_numpy_array(self):
        """Test count coercion with single-element numpy array."""
        assert _coerce_count_value(np.array([15])) == 15

    def test_coerce_count_value_with_plain_int(self):
        """Test count coercion with plain integer."""
        assert _coerce_count_value(20) == 20


class TestFrameworkErrorHandling:
    """Test error paths in framework.py."""

    def test_validate_config_with_nonexistent_calibration_file(self, tmp_path):
        """Test validation when calibration file doesn't exist."""
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(tmp_path / "nonexistent.json"),
            channel_config_path="/tmp/channel.json",
            classifier_path="/tmp/gmm.json",
            rpc_host="localhost",
        )

        framework = QubiCFramework()
        errors = framework.validate_config(config)

        assert any("Calibration file not found" in e for e in errors)

    def test_create_executor_with_missing_calibration_path(self):
        """Test executor creation when calibration_path is None."""
        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path="",  # Empty path
            channel_config_path="/tmp/channel.json",
            classifier_path="/tmp/gmm.json",
        )
        settings = MagicMock()
        framework = QubiCFramework()

        with pytest.raises(ExecutorError, match="calibration_path is required"):
            framework.create_executor(config, settings)

    def test_create_executor_with_qubic_root_option(
        self, qubic_example_qubitcfg_path: Path, qubic_example_channel_config_path: Path
    ):
        """Test executor creation with qubic_root option (for coverage)."""
        from coda_qubic.support import QubiCDependencies

        # Create fake dependency classes (not Mock objects to avoid InvalidSpecError)
        class FakeCircuitRunner:
            def __init__(self, *args, **kwargs):
                pass

        class FakeCircuitRunnerClient:
            def __init__(self, *args, **kwargs):
                pass

        class FakeFPGAConfig:
            pass

        class FakeJobManager:
            def __init__(self, *args, **kwargs):
                pass

            def collect_counts(self, *args, **kwargs):
                return [MagicMock()]

        class FakePLInterface:
            def __init__(self, *args, **kwargs):
                pass

        class FakeQChip:
            def __init__(self, *args, **kwargs):
                pass

        class FakeSimInterface:
            def __init__(self, *args, **kwargs):
                pass

        fake_deps = QubiCDependencies(
            CircuitRunner=FakeCircuitRunner,
            CircuitRunnerClient=FakeCircuitRunnerClient,
            FPGAConfig=FakeFPGAConfig,
            JobManager=FakeJobManager,
            PLInterface=FakePLInterface,
            QChip=FakeQChip,
            SimInterface=FakeSimInterface,
            load_channel_configs=lambda path: {},
        )

        config = DeviceConfig(
            framework="qubic",
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(qubic_example_qubitcfg_path),
            channel_config_path=str(qubic_example_channel_config_path),
            classifier_path="/tmp/gmm.json",
            runner_mode="local",
            use_sim=True,
            qubic_root="/some/path/to/qubic",  # This exercises _resolve_qubic_root
        )
        settings = MagicMock()
        framework = QubiCFramework()

        # Should work (with fake deps, qubic_root is passed but not actually used)
        executor = framework.create_executor(config, settings, dependencies=fake_deps)
        assert executor is not None


class TestDeviceErrorHandling:
    """Test error paths in device.py."""

    def test_extract_hardware_qubit_id_with_invalid_label(self):
        """Test hardware qubit ID extraction with invalid label."""
        from coda_qubic.device import _extract_hardware_qubit_id

        with pytest.raises(ValueError, match="Invalid hardware qubit label"):
            _extract_hardware_qubit_id("InvalidLabel")

    def test_seconds_to_ns_with_none(self):
        """Test time conversion with None value."""
        from coda_qubic.device import _seconds_to_ns

        assert _seconds_to_ns(None) == 0

    def test_extract_named_frequency_with_string(self):
        """Test named frequency extraction."""
        from coda_qubic.device import _extract_named_frequency

        assert _extract_named_frequency("Q1.freq") == "Q1.freq"
        assert _extract_named_frequency(123.45) is None


class TestSupportErrorHandling:
    """Test error paths in support.py."""

    def test_ensure_qubic_sys_path_with_no_qubic_root(self):
        """Test sys.path mutation when QUBIC_ROOT not set."""
        import os
        import sys

        from coda_qubic.support import ensure_qubic_sys_path

        original_path = sys.path.copy()
        original_env = os.environ.get("QUBIC_ROOT")

        try:
            # Clear QUBIC_ROOT
            if "QUBIC_ROOT" in os.environ:
                del os.environ["QUBIC_ROOT"]

            # Should do nothing when qubic_root is None and env var not set
            ensure_qubic_sys_path(None)

            # sys.path should be unchanged
            assert sys.path == original_path

        finally:
            # Restore environment
            sys.path = original_path
            if original_env:
                os.environ["QUBIC_ROOT"] = original_env

    def test_ensure_qubic_sys_path_with_nonexistent_path(self):
        """Test sys.path mutation with nonexistent path."""
        import sys
        from pathlib import Path

        from coda_qubic.support import ensure_qubic_sys_path

        original_path = sys.path.copy()

        try:
            # Use a path that definitely doesn't exist
            fake_root = Path("/nonexistent/qubic/path")
            ensure_qubic_sys_path(fake_root)

            # sys.path should be unchanged (no nonexistent paths added)
            assert sys.path == original_path

        finally:
            sys.path = original_path

    def test_load_qubic_dependencies_raises_runtime_error(self, monkeypatch):
        """Test that loading QubiC dependencies raises helpful error."""
        import builtins

        from coda_qubic.support import load_qubic_dependencies

        real_import = builtins.__import__
        vendor_roots = frozenset({"distproc", "qubic", "qubitconfig"})

        def guarded_import(
            name: str,
            globals: dict[str, object] | None = None,
            locals: dict[str, object] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            root = name.split(".", 1)[0]
            if root in vendor_roots:
                raise ImportError("simulated missing QubiC vendor stack")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", guarded_import)

        with pytest.raises(RuntimeError, match="QubiC dependencies are unavailable"):
            load_qubic_dependencies(Path("/nonexistent/path"))


class TestProtocolCompliance:
    """Test that our implementations properly implement the protocols."""

    def test_framework_is_runtime_checkable_protocol(self):
        """Verify Framework protocol is runtime checkable."""
        from self_service.frameworks.base import Framework

        from coda_qubic.framework import QubiCFramework

        # Should work with isinstance due to @runtime_checkable
        framework = QubiCFramework()
        assert isinstance(framework, Framework)

    def test_job_executor_protocol_has_required_methods(
        self, qubic_example_qubitcfg_path: Path
    ):
        """Verify QubiCJobRunner has required protocol methods."""
        from self_service.server.executor import JobExecutor

        from coda_qubic.device import QubiCDeviceSpec

        device = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        runner = QubiCJobRunner(MagicMock(), device)

        # Check protocol compliance
        assert hasattr(runner, "run")
        assert callable(runner.run)

        # Verify runtime type checking works (JobExecutor is @runtime_checkable)
        assert isinstance(runner, JobExecutor)

    def test_framework_protocol_has_all_required_methods(self):
        """Verify QubiCFramework has all protocol methods."""
        from coda_qubic.framework import QubiCFramework

        framework = QubiCFramework()

        # Check all required protocol methods/properties
        assert hasattr(framework, "name")
        assert hasattr(framework, "supported_targets")
        assert hasattr(framework, "validate_config")
        assert hasattr(framework, "create_executor")

        # Verify they're callable/accessible
        assert isinstance(framework.name, str)
        assert isinstance(framework.supported_targets, frozenset)
        assert callable(framework.validate_config)
        assert callable(framework.create_executor)
