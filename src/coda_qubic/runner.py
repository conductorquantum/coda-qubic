"""QubiC-backed job executor.

Implements the JobExecutor protocol for QubiC-based quantum hardware.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from coda_node.errors import ExecutorError
from coda_node.server.executor import ExecutionResult
from coda_node.server.ir import NativeGateIR

from coda_qubic.device import QubiCDeviceSpec
from coda_qubic.translator import (
    QubiCCircuitTranslator,
    TranslatedQubiCCircuit,
)


class QubiCJobRunner:
    """Executes NativeGateIR circuits on a QubiC stack.

    Implements the ``JobExecutor`` protocol from
    ``coda_node.server.executor``.  The protocol requires a single async
    ``run(ir, shots)`` method that returns ``ExecutionResult``.

    The ``JobExecutor`` protocol is decorated with ``@runtime_checkable``,
    enabling runtime type checks via ``isinstance``.
    """

    def __init__(
        self,
        job_manager: Any,
        device: QubiCDeviceSpec,
        native_gate_set: str = "cnot",
    ) -> None:
        self._job_manager = job_manager
        self._device = device
        self._native_gate_set = native_gate_set
        self._translator = QubiCCircuitTranslator(device)
        self._cancel_requested = threading.Event()

    async def run(self, ir: NativeGateIR, shots: int) -> ExecutionResult:
        self._cancel_requested.clear()
        return await asyncio.to_thread(self._execute, ir, shots)

    def cancel_current_job(self) -> None:
        self._cancel_requested.set()

    def _execute(self, ir: NativeGateIR, shots: int) -> ExecutionResult:
        started = time.monotonic()
        self._raise_if_cancelled()
        if ir.target != self._native_gate_set:
            raise ExecutorError(
                "QubiC target mismatch: "
                f"executor configured for '{self._native_gate_set}' IR but received '{ir.target}'"
            )
        try:
            translated = self._translator.translate(ir)
        except Exception as exc:
            raise ExecutorError(f"QubiC translation failed: {exc}") from exc
        self._raise_if_cancelled()

        try:
            results = self._job_manager.collect_counts(
                [translated.program],
                shots,
                reads_per_shot=1,
            )
        except Exception as exc:
            raise ExecutorError(f"QubiC execution failed: {exc}") from exc
        self._raise_if_cancelled()

        if len(results) != 1:
            raise ExecutorError(
                f"QubiC execution failed: Expected one QubiC result, got {len(results)}"
            )

        counts = _normalize_counts(results[0], translated)
        elapsed_ms = round((time.monotonic() - started) * 1000, 2)
        return ExecutionResult(
            counts=counts,
            execution_time_ms=elapsed_ms,
            shots_completed=shots,
        )

    @property
    def device(self) -> QubiCDeviceSpec:
        return self._device

    def _raise_if_cancelled(self) -> None:
        if self._cancel_requested.is_set():
            raise ExecutorError("QubiC execution cancelled")


def _normalize_counts(
    circuit_counts: Any,
    translated: TranslatedQubiCCircuit,
) -> dict[str, int]:
    source_qubits = list(circuit_counts.qubits)
    desired_qubits = list(translated.measurement_hardware_order)
    if sorted(source_qubits) != sorted(desired_qubits):
        raise ExecutorError(
            f"QubiC result_collection failed: QubiC returned qubits {source_qubits}, expected {desired_qubits}"
        )

    source_to_desired = [desired_qubits.index(qubit) for qubit in source_qubits]
    counts: dict[str, int] = {}
    for source_bits, raw_value in circuit_counts.count_dict.items():
        reordered_bits = ["0"] * len(source_bits)
        for source_index, bit in enumerate(source_bits):
            reordered_bits[source_to_desired[source_index]] = _coerce_bit_value(bit)
        counts["".join(reordered_bits)] = _coerce_count_value(raw_value)
    return counts


def _coerce_bit_value(raw_bit: Any) -> str:
    if hasattr(raw_bit, "item"):
        raw_bit = raw_bit.item()

    if isinstance(raw_bit, bool):
        return "1" if raw_bit else "0"

    try:
        numeric_bit = float(raw_bit)
    except (TypeError, ValueError) as exc:
        raise ExecutorError(
            f"QubiC result_collection failed: Unsupported readout bit value {raw_bit!r}"
        ) from exc

    if numeric_bit == 0.0:
        return "0"
    if numeric_bit == 1.0:
        return "1"

    raise ExecutorError(
        f"QubiC result_collection failed: Unsupported readout bit value {raw_bit!r}"
    )


def _coerce_count_value(raw_value: Any) -> int:
    if hasattr(raw_value, "tolist"):
        value = raw_value.tolist()
        if isinstance(value, list):
            if len(value) != 1:
                raise ExecutorError(
                    f"QubiC result_collection failed: Expected a single readout per shot, got {len(value)} read buckets"
                )
            return int(value[0])
        return int(value)
    if isinstance(raw_value, list):
        if len(raw_value) != 1:
            raise ExecutorError(
                f"QubiC result_collection failed: Expected a single readout per shot, got {len(raw_value)} read buckets"
            )
        return int(raw_value[0])
    return int(raw_value)
