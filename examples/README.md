# QubiC Configuration Examples

This directory contains example configuration files for the coda-qubic framework.

## Files

### Calibration Files

- **qubitcfg.json**: QubiC calibration file with a 20-qubit sparse-grid topology
  - Contains qubit frequencies, gate calibrations, and two-qubit connectivity
  - Includes 20 qubits (Q0-Q19) arranged in a 4x5 grid with a few missing couplers
  - All 20 qubits form a single connected component (no subset selection needed)
  - Readout LO phases (`rdlo`) are set to 0 so the generic GMM classifier
    below produces correct discrimination. On real hardware these phases are
    non-zero and the classifier must be calibrated to match.

- **channel_config.json**: FPGA channel configuration
  - Maps logical channels to physical FPGA cores for all 20 qubits
  - Defines memory locations for envelopes, frequencies, and accumulators
  - Required for QubiC hardware compilation

- **gmm_classifier.json**: Gaussian Mixture Model classifier (placeholder)
  - Used for single-shot readout discrimination for all 20 qubits
  - Assumes readout IQ clouds align with the I-axis (rdlo phase = 0).
    On real hardware, replace with per-qubit calibrated parameters.

### Device Configuration Examples

Three device configuration templates are provided for different execution modes:

#### 1. RPC Mode (`device_rpc.yaml`)

Connects to a remote QubiC RPC server:

```yaml
framework: qubic
target: cnot
num_qubits: 20
calibration_path: ./qubitcfg.json
channel_config_path: ./channel_config.json
classifier_path: ./gmm_classifier.json
runner_mode: rpc
rpc_host: localhost
rpc_port: 9095
```

**Use when**: QubiC is running as a service on another machine or container.

#### 2. Simulation Mode (`device_sim.yaml`)

Uses QubiC's built-in simulator:

```yaml
framework: qubic
target: cnot
num_qubits: 20
calibration_path: ./qubitcfg.json
channel_config_path: ./channel_config.json
classifier_path: ./gmm_classifier.json
runner_mode: local
use_sim: true
```

**Use when**: Testing without hardware or when QubiC hardware is unavailable.

> **Simulator limitations** — see [Pulse Simulator Limitations](#pulse-simulator-limitations)
> below before interpreting results from `use_sim: true`.

#### 3. Local Hardware Mode (`device_hardware.yaml`)

Executes directly on QubiC FPGA hardware:

```yaml
framework: qubic
target: cnot
num_qubits: 20
calibration_path: ./qubitcfg.json
channel_config_path: ./channel_config.json
classifier_path: ./gmm_classifier.json
runner_mode: local
xsa_commit: abc123def456789
```

**Use when**: Running on the same machine as QubiC hardware with direct FPGA access.

## Usage

### Basic Example

```python
from self_service.server.ir import NativeGateIR, GateOp, IRMetadata
from coda_qubic.config import QubiCConfig
from coda_qubic.executor_factory import build_executor

# Load device configuration
config = QubiCConfig.from_yaml("examples/device_sim.yaml")

# Create executor
executor = build_executor(config)

# Define a simple circuit on the sparse grid
ir = NativeGateIR(
    num_qubits=20,
    target="cnot",
    gates=[
        GateOp(gate="x90", qubits=[0], params=[]),
        GateOp(gate="cnot", qubits=[1, 0], params=[]),
    ],
    measurements=[0, 1],
    metadata=IRMetadata(
        source_hash="example",
        compiled_at="2026-03-16T00:00:00Z",
    ),
)

# Execute
result = await executor.run(ir, shots=1000)
print(f"Counts: {result.counts}")
print(f"Execution time: {result.execution_time_ms}ms")
```

### With coda-self-service

When running via coda-self-service, set the executor factory:

```bash
CODA_EXECUTOR_FACTORY=coda_qubic.executor_factory:create_executor \
CODA_DEVICE_CONFIG=examples/device_sim.yaml \
uv run coda start --token <your-token>
```

## Device Topology

The example `qubitcfg.json` defines a 20-qubit system (Q0-Q19) arranged in a
simple 4x5 grid with a few missing horizontal edges. All 20 qubits form a single connected component with
24 directed CNOT edges:

```
Q0 --- Q1 --- Q2     Q3 --- Q4
|      |      |      |      |
Q5 --- Q6     Q7 --- Q8     Q9
|      |      |      |      |
Q10 -- Q11 -- Q12    Q13    Q14
|      |      |      |      |
Q15 -- Q16    Q17    Q18 -- Q19
```

Most qubits have 2-3 neighbours, with the interior grid qubits reaching degree 4 where horizontal and vertical couplers both exist.
Logical qubit indices map directly to hardware labels: logical 0 = Q0, logical 1 = Q1, etc.

**Available directed CNOTs** (24 edges, higher-index qubit is control):

| Control → Target | Control → Target | Control → Target |
|---|---|---|
| Q1 → Q0 | Q10 → Q5 | Q17 → Q12 |
| Q2 → Q1 | Q11 → Q6 | Q18 → Q13 |
| Q4 → Q3 | Q12 → Q7 | Q19 → Q14 |
| Q5 → Q0 | Q13 → Q8 | Q16 → Q15 |
| Q6 → Q1 | Q14 → Q9 | Q19 → Q18 |
| Q6 → Q5 | Q15 → Q10 | |
| Q7 → Q2 | Q16 → Q11 | |
| Q8 → Q3 | Q11 → Q10 | |
| Q8 → Q7 | Q12 → Q11 | |
| Q9 → Q4 | | |

The framework uses these gates for both `cz` (via CZ = H-CNOT-H) and `cnot` (native) IR targets.

## Pulse Simulator Limitations

When `use_sim: true` is set, circuits run on LBNL's QubiC **pulse-level
simulator** (`qubic.sim.sim_interface`), not a gate-level statevector
simulator.  This has several important implications:

### Not a perfect gate simulator

The pulse simulator models microwave drive waveforms, cross-resonance
pulses, and readout discrimination at the signal level.  Gate fidelity
depends entirely on the calibration parameters in `qubitcfg.json`.  The
example calibration is representative of real hardware but is **not**
perfectly tuned, so results will diverge from ideal gate-model
expectations — particularly for deeper circuits.

The checked-in example classifier file is only for local smoke testing.  For
real lab runs, use the classifier file or live-fit workflow provided by the
hardware team; the current upstream simulator does not emit realistic,
state-dependent IQ clouds for local classifier training.

### Coherent error accumulation

Errors from the pulse simulator are **coherent** (systematic
over/under-rotations), not depolarising noise.  These errors compound
predictably through a circuit rather than averaging out:

- **Shallow circuits** (1–3 two-qubit gates): results are typically
  qualitatively correct, with the dominant output state matching the
  ideal expectation.
- **Moderate-depth circuits** (5–15 two-qubit gates): noticeable
  probability leakage to nearby states; the target state is still the
  most probable.
- **Deep circuits** (>15 two-qubit gates, e.g. multi-iteration Grover
  with SWAP routing): accumulated phase errors can destroy the
  interference pattern entirely, producing distributions that bear little
  resemblance to the ideal output (e.g. a 50/50 split instead of a
  single dominant state).

### Impact of SWAP routing

When the cloud compiler performs topology-aware routing (inserting SWAP
gates to respect device connectivity), circuit depth increases
substantially.  Each SWAP decomposes into 3 CZ gates, and each CZ is
translated to 2 Hadamard pulse sequences + 1 cross-resonance pulse:

```
SWAP ≈ 3 × CZ ≈ 3 × (2 Hadamard + 1 CR pulse) = 6 single-qubit + 3 CR operations
```

For a 3-qubit Grover's search on a linear chain (`Q1–Q2–Q3`), a single
Toffoli decomposition with routing can add 2–4 SWAPs, increasing the CR
pulse count by 6–12.  On the pulse simulator, this is often enough to
break algorithms that rely on precise multi-gate interference.

### When to trust the simulator

| Use case | Trustworthy? |
|---|---|
| Integration testing (pipeline doesn't crash) | Yes |
| Verifying gate decomposition / translation | Yes (shallow circuits) |
| Qualitative algorithm behaviour (1 iteration) | Roughly |
| Quantitative algorithm fidelity | No |
| Multi-iteration algorithms with SWAP routing | No |

For quantitative verification of compiled circuits, use Qiskit's
`Statevector` or `AerSimulator` on the NativeGateIR gate sequence before
sending it to the QubiC translator.

## Requirements

### For Simulation

- Python 3.12+
- coda-self-service
- QubiC vendor dependencies (qubic, distproc, qubitconfig)
  - Set `QUBIC_ROOT` environment variable or use `qubic_root` config option

### For RPC Mode

- QubiC RPC server running on specified host/port
- Network access to RPC server

### For Hardware Mode

- Physical QubiC hardware
- Direct FPGA access
- Valid `xsa_commit` hash for bitstream

## Troubleshooting

**Error: "QubiC dependencies are unavailable"**

Set the `QUBIC_ROOT` environment variable or add `qubic_root` to your device config:

```yaml
qubic_root: /path/to/qubic/checkout
```

**Error: "No usable two-qubit calibrations found"**

The `qubitcfg.json` must contain at least one CNOT gate with non-zero pulse durations. Check that:
- Both qubits have X90 and read gates defined
- The CR gate has non-zero `twidth`
- The corresponding CNOT gate exists

**Error: "num_qubits does not match QubiC device size"**

The `num_qubits` in your device config must match the size of the largest connected component in `qubitcfg.json`. The framework derives this automatically from the calibration file.

## Calibration File Format

The `qubitcfg.json` follows QubiC's standard format:

```json
{
    "Qubits": {
        "Q0": {
            "freq": 4460029188.07884,
            "readfreq": 6554327471.963202
        }
    },
    "Gates": {
        "Q0X90": [{"freq": "Q0.freq", "dest": "Q0.qdrv", "twidth": 2.4e-08, "amp": 0.11, ...}],
        "Q0read": [{"freq": "Q0.readfreq", "dest": "Q0.rdrv", "twidth": 2e-06, "amp": 0.02, ...}],
        "Q1Q0CR": [{"freq": "Q0.freq", "dest": "Q1.qdrv", "twidth": 3e-07, "amp": 0.30, ...}],
        "Q1Q0CNOT": [{"gate": "virtualz", ...}, {"gate": "Q1Q0CR"}, ...]
    }
}
```

See `qubitcfg.json` for a complete example with 20 qubits on a hex grid.
