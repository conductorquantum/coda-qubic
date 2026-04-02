"""Noisy quantum device simulation using Qiskit Aer.

Provides :class:`QiskitNoisySimulator`, a :class:`JobExecutor`-compatible
backend that converts :class:`NativeGateIR` directly to Qiskit circuits
and runs them on ``AerSimulator`` with a configurable depolarizing noise
model.  No QubiC vendor stack is required.
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from typing import Any

from coda_node.errors import ExecutorError
from coda_node.server.executor import ExecutionResult
from coda_node.server.ir import NativeGateIR

from coda_qubic.device import (
    DirectedCNOTCalibration,
    QubiCDeviceSpec,
    QubiCSingleQubitCalibration,
)

try:
    from qiskit import QuantumCircuit
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import (
        NoiseModel,
        depolarizing_error,
        thermal_relaxation_error,
    )

    _QISKIT_AVAILABLE = True
except ImportError:
    _QISKIT_AVAILABLE = False

__all__ = ["QiskitNoisySimulator"]

logger = logging.getLogger(__name__)


def _require_qiskit() -> None:
    if not _QISKIT_AVAILABLE:
        raise RuntimeError(
            "Qiskit simulation requires 'qiskit' and 'qiskit-aer'. "
            "Install them with: pip install 'coda-qubic[qiskit]'"
        )


_SINGLE_QUBIT_GATE_NAMES = {"rx", "ry", "rz", "x90", "y_minus_90", "virtual_z", "id"}
_TWO_QUBIT_GATE_NAMES = {"cz", "cnot", "iswap", "cp"}


class QiskitNoisySimulator:
    """Execute NativeGateIR circuits via Qiskit AerSimulator with noise.

    Implements the ``JobExecutor`` protocol from
    ``coda_node.server.executor``.
    """

    def __init__(
        self,
        num_qubits: int,
        target: str,
        *,
        single_qubit_error_rate: float = 0.001,
        two_qubit_error_rate: float = 0.01,
        measurement_error_rate: float = 0.01,
        t1_ns: float | None = None,
        t2_ns: float | None = None,
    ) -> None:
        _require_qiskit()
        self._num_qubits = num_qubits
        self._target = target
        self._single_qubit_error_rate = single_qubit_error_rate
        self._two_qubit_error_rate = two_qubit_error_rate
        self._measurement_error_rate = measurement_error_rate
        self._t1_ns = t1_ns
        self._t2_ns = t2_ns
        self._device = _synthesize_device_spec(num_qubits)
        self._noise_model = self._build_noise_model()
        self._cancel_requested = threading.Event()
        self._current_job: Any | None = None

    async def run(self, ir: NativeGateIR, shots: int) -> ExecutionResult:
        self._cancel_requested.clear()
        return await asyncio.to_thread(self._execute, ir, shots)

    def cancel_current_job(self) -> None:
        self._cancel_requested.set()
        current_job = self._current_job
        if current_job is None:
            return

        cancel = getattr(current_job, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                logger.warning("Failed to cancel active Qiskit Aer job", exc_info=True)

    def _execute(self, ir: NativeGateIR, shots: int) -> ExecutionResult:
        started = time.monotonic()
        self._raise_if_cancelled()
        if ir.target != self._target:
            raise ExecutorError(
                f"Qiskit sim target mismatch: configured for '{self._target}' "
                f"but received '{ir.target}'"
            )
        if ir.num_qubits > self._num_qubits:
            raise ExecutorError(
                f"IR requires {ir.num_qubits} qubits but simulator "
                f"is configured for {self._num_qubits}"
            )

        try:
            circuit = _build_circuit(ir, t1_ns=self._t1_ns, t2_ns=self._t2_ns)
        except Exception as exc:
            raise ExecutorError(f"Qiskit circuit construction failed: {exc}") from exc
        self._raise_if_cancelled()

        try:
            backend = AerSimulator(noise_model=self._noise_model)
            job = backend.run(circuit, shots=shots)
            self._current_job = job
            self._raise_if_cancelled()
            result = job.result()
            raw_counts = result.get_counts(circuit)
        except Exception as exc:
            raise ExecutorError(f"Qiskit simulation failed: {exc}") from exc
        finally:
            self._current_job = None
        self._raise_if_cancelled()

        counts = _reformat_counts(raw_counts, ir.measurements)
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
            raise ExecutorError("Qiskit simulation cancelled")

    def _build_noise_model(self) -> Any:
        noise_model = NoiseModel()

        has_thermal_relaxation = self._t1_ns is not None and self._t2_ns is not None

        if self._single_qubit_error_rate > 0:
            sq_error = depolarizing_error(self._single_qubit_error_rate, 1)
            sq_gates = ["rx", "ry", "rz"]
            if not has_thermal_relaxation:
                sq_gates.append("id")
            for gate in sq_gates:
                noise_model.add_all_qubit_quantum_error(sq_error, gate)

        if self._two_qubit_error_rate > 0:
            tq_error = depolarizing_error(self._two_qubit_error_rate, 2)
            for gate in ("cx", "cz", "iswap", "cp"):
                noise_model.add_all_qubit_quantum_error(tq_error, gate)

        if self._measurement_error_rate > 0:
            meas_error = depolarizing_error(self._measurement_error_rate, 1)
            noise_model.add_all_qubit_quantum_error(meas_error, "measure")

        return noise_model


def _build_circuit(
    ir: NativeGateIR,
    *,
    t1_ns: float | None = None,
    t2_ns: float | None = None,
) -> QuantumCircuit:
    """Convert a :class:`NativeGateIR` into a Qiskit :class:`QuantumCircuit`.

    When *t1_ns* and *t2_ns* are provided, ``id`` (delay) gates are
    replaced with thermal relaxation channels whose strength is
    proportional to the gate's duration parameter.  This enables
    realistic T1/T2 decay simulation for characterization experiments.
    """
    qc = QuantumCircuit(ir.num_qubits, len(ir.measurements))
    use_relaxation = t1_ns is not None and t2_ns is not None

    for gate_op in ir.gates:
        gate = gate_op.gate.value
        qubits = gate_op.qubits
        params = gate_op.params

        if gate == "rx":
            qc.rx(params[0], qubits[0])
        elif gate == "ry":
            qc.ry(params[0], qubits[0])
        elif gate == "rz":
            qc.rz(params[0], qubits[0])
        elif gate == "cz":
            qc.cz(qubits[0], qubits[1])
        elif gate == "cnot":
            qc.cx(qubits[0], qubits[1])
        elif gate == "x90":
            qc.rx(math.pi / 2, qubits[0])
        elif gate == "y_minus_90":
            qc.ry(-math.pi / 2, qubits[0])
        elif gate == "virtual_z":
            qc.rz(params[0], qubits[0])
        elif gate == "id":
            if use_relaxation:
                assert t1_ns is not None and t2_ns is not None
                _append_thermal_relaxation(
                    qc,
                    qubits[0],
                    params[0],
                    t1_ns,
                    t2_ns,
                )
            else:
                qc.id(qubits[0])
        elif gate == "iswap":
            qc.iswap(qubits[0], qubits[1])
        elif gate == "cp":
            qc.cp(params[0], qubits[0], qubits[1])
        else:
            raise ValueError(f"Unsupported NativeGate for Qiskit simulation: {gate}")

    for clbit_index, qubit in enumerate(ir.measurements):
        qc.measure(qubit, clbit_index)

    return qc


_MIN_DELAY_NS = 0.1


def _append_thermal_relaxation(
    qc: QuantumCircuit,
    qubit: int,
    delay_ns: float,
    t1_ns: float,
    t2_ns: float,
) -> None:
    """Insert a thermal relaxation channel for a delay gate.

    For very short delays the relaxation is negligible and the gate
    is replaced with a plain identity.
    """
    if delay_ns < _MIN_DELAY_NS:
        qc.id(qubit)
        return

    t2_clamped = min(t2_ns, 2.0 * t1_ns)
    error = thermal_relaxation_error(t1_ns, t2_clamped, delay_ns)
    qc.append(error.to_instruction(), [qubit])


def _reformat_counts(
    raw_counts: dict[str, int],
    measurements: list[int],
) -> dict[str, int]:
    """Normalise Qiskit result counts to match the coda-node convention.

    Qiskit returns bitstrings in big-endian order across all qubits in the
    classical register.  We already mapped measurements[i] -> clbit i when
    building the circuit, so the raw keys are already in measurement order.
    The only thing left is to strip any whitespace Qiskit may insert.
    """
    result: dict[str, int] = {}
    expected_width = len(measurements)
    for bitstring, count in raw_counts.items():
        key = bitstring.replace(" ", "")
        if len(key) != expected_width:
            raise ExecutorError(
                f"Qiskit returned bitstring '{key}' with width {len(key)}, "
                f"expected {expected_width}"
            )
        result[key] = count
    return result


def _synthesize_device_spec(num_qubits: int) -> QubiCDeviceSpec:
    """Build a synthetic :class:`QubiCDeviceSpec` with linear-chain connectivity.

    Generates Q1 -- Q2 -- ... -- Qn with placeholder calibration values
    so the node can report device topology via heartbeats.
    """
    hardware_labels = tuple(f"Q{i + 1}" for i in range(num_qubits))

    qubits: dict[int, QubiCSingleQubitCalibration] = {}
    for logical, hw_label in enumerate(hardware_labels):
        qubits[logical] = QubiCSingleQubitCalibration(
            logical_qubit=logical,
            hardware_qubit=hw_label,
            drive_frequency_hz=5.0e9 + logical * 0.1e9,
            drive_amplitude=0.15,
            x90_duration_ns=24,
            readout_frequency_hz=6.5e9 + logical * 0.1e9,
            readout_amplitude=0.02,
            readout_duration_ns=2000,
            readout_phase_rad=0.0,
        )

    directed_cnot_edges: dict[tuple[int, int], DirectedCNOTCalibration] = {}
    for i in range(num_qubits - 1):
        control, target = i + 1, i
        ctrl_hw = hardware_labels[control]
        tgt_hw = hardware_labels[target]
        directed_cnot_edges[(control, target)] = DirectedCNOTCalibration(
            control_logical=control,
            target_logical=target,
            control_hardware=ctrl_hw,
            target_hardware=tgt_hw,
            cr_duration_ns=300,
            cr_amplitude=0.30,
            target_pulse_duration_ns=32,
            target_pulse_amplitude=0.20,
        )

    return QubiCDeviceSpec(
        logical_to_hardware=hardware_labels,
        qubits=qubits,
        directed_cnot_edges=directed_cnot_edges,
    )
