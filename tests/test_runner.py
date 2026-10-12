from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from coda_node.server.executor import ExecutionResult
from coda_node.server.ir import GateOp, IRMetadata, NativeGate, NativeGateIR

from coda_qubic.device import QubiCDeviceSpec
from coda_qubic.runner import QubiCJobRunner, _normalize_counts


class FakeCircuitCounts:
    def __init__(self) -> None:
        self.qubits = ["Q1", "Q3"]
        self.count_dict = OrderedDict(
            {
                (0, 0): np.array([2]),
                (0, 1): np.array([7]),
                (1, 0): np.array([3]),
                (1, 1): np.array([1]),
            }
        )


class FakeCircuitCountsThreeQubit:
    def __init__(self) -> None:
        self.qubits = ["Q1", "Q2", "Q3"]
        self.count_dict = OrderedDict(
            {
                (0, 0, 1): np.array([4]),
                (1, 0, 0): np.array([5]),
                (1, 1, 0): np.array([6]),
            }
        )


class FakeCircuitCountsFloatBits:
    def __init__(self) -> None:
        self.qubits = ["Q1", "Q3"]
        self.count_dict = OrderedDict(
            {
                (0.0, 1.0): np.array([7]),
                (np.float64(1.0), np.float64(0.0)): np.array([3]),
            }
        )


class FakeCircuitCountsMultiRead:
    def __init__(self) -> None:
        self.qubits = ["Q1", "Q3"]
        self.count_dict = OrderedDict({(0, 1): np.array([3, 9])})


class FakeJobManager:
    def __init__(self) -> None:
        self.last_program_list: list[list[dict[str, Any]]] | None = None
        self.last_shots: int | None = None
        self.last_reads_per_shot: int | None = None

    def collect_counts(
        self,
        program_list: list[list[dict[str, Any]]],
        shots: int,
        reads_per_shot: int = 1,
    ) -> list[FakeCircuitCounts]:
        self.last_program_list = program_list
        self.last_shots = shots
        self.last_reads_per_shot = reads_per_shot
        return [FakeCircuitCounts()]


class BlockingJobManager(FakeJobManager):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def collect_counts(
        self,
        program_list: list[list[dict[str, Any]]],
        shots: int,
        reads_per_shot: int = 1,
    ) -> list[FakeCircuitCounts]:
        self.last_program_list = program_list
        self.last_shots = shots
        self.last_reads_per_shot = reads_per_shot
        self.started.set()
        self.release.wait(timeout=1.0)
        return [FakeCircuitCounts()]


def _ir() -> NativeGateIR:
    return NativeGateIR(
        num_qubits=3,
        target="cz",
        gates=[GateOp(gate=NativeGate.CZ, qubits=[0, 1], params=[])],
        measurements=[2, 0],
        metadata=IRMetadata(
            source_hash="sha256:test",
            compiled_at="2026-03-13T00:00:00Z",
        ),
    )


def _native_ir() -> NativeGateIR:
    return NativeGateIR(
        num_qubits=3,
        target="cnot",
        gates=[GateOp(gate=NativeGate.CNOT, qubits=[1, 0], params=[])],
        measurements=[2, 0],
        metadata=IRMetadata(
            source_hash="sha256:test",
            compiled_at="2026-03-13T00:00:00Z",
        ),
    )


class TestQubiCJobRunner:
    def test_run_reorders_counts_to_measurement_order(
        self, qubic_example_qubitcfg_path: Path
    ) -> None:
        device = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        job_manager = FakeJobManager()
        runner = QubiCJobRunner(
            job_manager=job_manager,
            device=device,
            native_gate_set="cz",
        )

        result = asyncio.run(runner.run(_ir(), 13))

        assert isinstance(result, ExecutionResult)
        assert result.shots_completed == 13
        assert result.counts == {
            "00": 2,
            "10": 7,
            "01": 3,
            "11": 1,
        }
        assert job_manager.last_shots == 13
        assert job_manager.last_reads_per_shot == 1
        assert job_manager.last_program_list is not None
        assert job_manager.last_program_list[0][-2:] == [
            {"name": "read", "qubit": ["Q3"]},
            {"name": "read", "qubit": ["Q1"]},
        ]

    def test_run_supports_qubic_native_ir(
        self, qubic_example_qubitcfg_path: Path
    ) -> None:
        device = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        job_manager = FakeJobManager()
        runner = QubiCJobRunner(
            job_manager=job_manager,
            device=device,
            native_gate_set="cnot",
        )

        result = asyncio.run(runner.run(_native_ir(), 9))

        assert isinstance(result, ExecutionResult)
        assert result.shots_completed == 9
        assert job_manager.last_program_list is not None
        assert job_manager.last_program_list[0][0] == {
            "name": "CNOT",
            "qubit": ["Q2", "Q1"],
        }

    def test_run_rejects_target_mismatch(
        self, qubic_example_qubitcfg_path: Path
    ) -> None:
        device = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        job_manager = FakeJobManager()
        runner = QubiCJobRunner(
            job_manager=job_manager,
            device=device,
            native_gate_set="cnot",
        )

        with pytest.raises(Exception, match="QubiC target mismatch"):
            asyncio.run(runner.run(_ir(), 9))

    def test_cancel_current_job_aborts_after_collect_counts(
        self, qubic_example_qubitcfg_path: Path
    ) -> None:
        device = QubiCDeviceSpec.from_qubitcfg(qubic_example_qubitcfg_path)
        job_manager = BlockingJobManager()
        runner = QubiCJobRunner(
            job_manager=job_manager,
            device=device,
            native_gate_set="cz",
        )

        async def scenario() -> None:
            task = asyncio.create_task(runner.run(_ir(), 13))
            started = await asyncio.to_thread(job_manager.started.wait, 1.0)
            assert started is True
            runner.cancel_current_job()
            job_manager.release.set()
            with pytest.raises(Exception, match="QubiC execution cancelled"):
                await task

        asyncio.run(scenario())

    def test_normalize_counts_handles_three_qubit_permutation(self) -> None:
        translated = type(
            "Translated",
            (),
            {"measurement_hardware_order": ["Q3", "Q1", "Q2"]},
        )()

        counts = _normalize_counts(FakeCircuitCountsThreeQubit(), translated)

        assert counts == {
            "100": 4,
            "010": 5,
            "011": 6,
        }

    def test_normalize_counts_accepts_float_bit_labels(self) -> None:
        translated = type(
            "Translated",
            (),
            {"measurement_hardware_order": ["Q3", "Q1"]},
        )()

        counts = _normalize_counts(FakeCircuitCountsFloatBits(), translated)

        assert counts == {
            "10": 7,
            "01": 3,
        }

    def test_normalize_counts_rejects_mismatched_qubit_sets(self) -> None:
        translated = type(
            "Translated",
            (),
            {"measurement_hardware_order": ["Q3", "Q2"]},
        )()

        with pytest.raises(Exception, match="QubiC returned qubits"):
            _normalize_counts(FakeCircuitCounts(), translated)

    def test_normalize_counts_rejects_multi_read_results(self) -> None:
        translated = type(
            "Translated",
            (),
            {"measurement_hardware_order": ["Q3", "Q1"]},
        )()

        with pytest.raises(Exception, match="Expected a single readout per shot"):
            _normalize_counts(FakeCircuitCountsMultiRead(), translated)
