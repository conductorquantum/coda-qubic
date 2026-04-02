"""Tests for the shared common utilities module."""

from __future__ import annotations

import math

import numpy as np
import pytest
from coda_node.server.ir import NativeGate

from coda_qubic.benchmarks import RBFitResult
from coda_qubic.common import (
    HALF_PI,
    NEG_HALF_PI,
    PI,
    ExponentialDecayFit,
    FitResult,
    delay_op,
    experiment_metadata,
    fit_exponential_decay,
    x90_ops,
    x180_ops,
)
from coda_qubic.experiments import T1FitResult, T2FitResult

# ===================================================================
# 1. Angular constants
# ===================================================================


class TestConstants:
    def test_half_pi(self) -> None:
        assert pytest.approx(math.pi / 2) == HALF_PI

    def test_pi(self) -> None:
        assert pytest.approx(math.pi) == PI

    def test_neg_half_pi(self) -> None:
        assert pytest.approx(-math.pi / 2) == NEG_HALF_PI


# ===================================================================
# 2. experiment_metadata
# ===================================================================


class TestExperimentMetadata:
    def test_source_hash_contains_label(self) -> None:
        meta = experiment_metadata("my-label")
        assert meta.source_hash == "sha256:my-label"

    def test_compiled_at_is_fixed(self) -> None:
        meta = experiment_metadata("any")
        assert meta.compiled_at == "2026-01-01T00:00:00Z"

    def test_different_labels_produce_different_hashes(self) -> None:
        m1 = experiment_metadata("alpha")
        m2 = experiment_metadata("beta")
        assert m1.source_hash != m2.source_hash


# ===================================================================
# 3. Gate operation helpers
# ===================================================================


class TestX90Ops:
    def test_cnot_target_returns_x90(self) -> None:
        ops = x90_ops(0, "cnot")
        assert len(ops) == 1
        assert ops[0].gate == NativeGate.X90
        assert ops[0].qubits == [0]
        assert ops[0].params == []

    def test_cz_target_returns_rx_half_pi(self) -> None:
        ops = x90_ops(0, "cz")
        assert len(ops) == 1
        assert ops[0].gate == NativeGate.RX
        assert ops[0].qubits == [0]
        assert len(ops[0].params) == 1
        assert math.isclose(ops[0].params[0], math.pi / 2)

    def test_qubit_index_is_propagated(self) -> None:
        for q in (0, 3, 7):
            ops = x90_ops(q, "cnot")
            assert ops[0].qubits == [q]


class TestX180Ops:
    def test_cnot_target_returns_two_x90(self) -> None:
        ops = x180_ops(0, "cnot")
        assert len(ops) == 2
        for op in ops:
            assert op.gate == NativeGate.X90
            assert op.qubits == [0]
            assert op.params == []

    def test_cz_target_returns_rx_pi(self) -> None:
        ops = x180_ops(0, "cz")
        assert len(ops) == 1
        assert ops[0].gate == NativeGate.RX
        assert ops[0].qubits == [0]
        assert math.isclose(ops[0].params[0], math.pi)

    def test_qubit_index_is_propagated(self) -> None:
        for q in (1, 5):
            ops = x180_ops(q, "cz")
            assert ops[0].qubits == [q]


class TestDelayOp:
    def test_returns_id_gate(self) -> None:
        op = delay_op(0, 500.0)
        assert op.gate == NativeGate.ID
        assert op.qubits == [0]
        assert op.params == [500.0]

    def test_delay_duration_is_preserved(self) -> None:
        op = delay_op(2, 1234.5)
        assert op.params[0] == 1234.5

    def test_qubit_index_is_propagated(self) -> None:
        op = delay_op(4, 100.0)
        assert op.qubits == [4]


# ===================================================================
# 4. FitResult Protocol
# ===================================================================


class TestFitResultProtocol:
    def test_exponential_decay_fit_satisfies_protocol(self) -> None:
        fit = ExponentialDecayFit(tau=5000.0, fit_amplitude=0.9, fit_offset=0.05)
        assert isinstance(fit, FitResult)

    def test_t1_fit_result_satisfies_protocol(self) -> None:
        fit = T1FitResult(t1_ns=5000.0, fit_amplitude=0.9, fit_offset=0.05)
        assert isinstance(fit, FitResult)

    def test_t2_fit_result_satisfies_protocol(self) -> None:
        fit = T2FitResult(
            t2_ns=3000.0, fit_amplitude=0.5, fit_offset=0.5, frequency_hz=0.0
        )
        assert isinstance(fit, FitResult)

    def test_rb_fit_result_satisfies_protocol(self) -> None:
        fit = RBFitResult(
            depolarizing_parameter=0.99,
            average_gate_fidelity=0.995,
            fit_amplitude=0.5,
            fit_offset=0.5,
        )
        assert isinstance(fit, FitResult)

    def test_protocol_fields_accessible(self) -> None:
        fit: FitResult = ExponentialDecayFit(
            tau=1000.0, fit_amplitude=0.8, fit_offset=0.1
        )
        assert fit.fit_amplitude == 0.8
        assert fit.fit_offset == 0.1


# ===================================================================
# 5. ExponentialDecayFit dataclass
# ===================================================================


class TestExponentialDecayFit:
    def test_fields_are_readonly(self) -> None:
        fit = ExponentialDecayFit(tau=100.0, fit_amplitude=0.5, fit_offset=0.5)
        with pytest.raises(AttributeError):
            fit.tau = 200.0  # type: ignore[misc]

    def test_equality(self) -> None:
        a = ExponentialDecayFit(tau=100.0, fit_amplitude=0.5, fit_offset=0.5)
        b = ExponentialDecayFit(tau=100.0, fit_amplitude=0.5, fit_offset=0.5)
        assert a == b


# ===================================================================
# 6. Exponential decay fitting
# ===================================================================


class TestFitExponentialDecay:
    def test_fit_perfect_exponential(self) -> None:
        tau_true = 5000.0
        delays = [0.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 12000.0]
        values = [1.0 * np.exp(-t / tau_true) for t in delays]

        result = fit_exponential_decay(delays, values)
        assert isinstance(result, ExponentialDecayFit)
        assert abs(result.tau - tau_true) / tau_true < 0.05

    def test_fit_with_offset(self) -> None:
        tau_true = 3000.0
        a_true = 0.9
        b_true = 0.05
        delays = [0.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0]
        values = [a_true * np.exp(-t / tau_true) + b_true for t in delays]

        result = fit_exponential_decay(delays, values)
        assert abs(result.tau - tau_true) / tau_true < 0.05
        assert abs(result.fit_amplitude - a_true) < 0.05
        assert abs(result.fit_offset - b_true) < 0.05

    def test_fit_noisy_data(self) -> None:
        rng = np.random.default_rng(42)
        tau_true = 10000.0
        delays = [0.0, 1000.0, 2000.0, 5000.0, 10000.0, 20000.0, 30000.0]
        values = [
            float(
                np.clip(0.9 * np.exp(-t / tau_true) + 0.05 + rng.normal(0, 0.02), 0, 1)
            )
            for t in delays
        ]

        result = fit_exponential_decay(delays, values)
        assert 0.5 * tau_true < result.tau < 2.0 * tau_true

    def test_result_satisfies_fit_result_protocol(self) -> None:
        delays = [0.0, 1000.0, 2000.0, 4000.0]
        values = [1.0 * np.exp(-t / 5000.0) for t in delays]
        result = fit_exponential_decay(delays, values)
        assert isinstance(result, FitResult)
