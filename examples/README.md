# QubiC Configuration Examples

This directory contains example configuration files for the coda-qubic framework.

## Files

### Calibration Files

- **qubitcfg.json**: Real QubiC calibration file from LBNL hardware
  - Contains qubit frequencies, gate calibrations, and two-qubit connectivity
  - Includes 8 qubits (Q0-Q7) with CNOT gates for adjacent pairs
  - Framework automatically derives largest connected component (4 qubits: Q0-Q3)

- **channel_config.json**: FPGA channel configuration
  - Maps logical channels to physical FPGA cores
  - Defines memory locations for envelopes, frequencies, and accumulators
  - Required for QubiC hardware compilation

- **gmm_classifier.json**: Gaussian Mixture Model classifier (placeholder)
  - Used for single-shot readout discrimination
  - **Note**: This is a minimal placeholder. Replace with actual calibrated parameters.

### Device Configuration Examples

Three device configuration templates are provided for different execution modes:

#### 1. RPC Mode (`device_rpc.yaml`)

Connects to a remote QubiC RPC server:

```yaml
framework: qubic
target: superconducting_cnot
num_qubits: 3
calibration_path: ./qubitcfg.json
channel_config_path: ./channel_config.json
classifier_path: ./gmm_classifier.json
runner_mode: rpc
rpc_host: localhost
rpc_port: 9734
```

**Use when**: QubiC is running as a service on another machine or container.

#### 2. Simulation Mode (`device_sim.yaml`)

Uses QubiC's built-in simulator:

```yaml
framework: qubic
target: superconducting_cnot
num_qubits: 3
calibration_path: ./qubitcfg.json
channel_config_path: ./channel_config.json
classifier_path: ./gmm_classifier.json
runner_mode: local
use_sim: true
```

**Use when**: Testing without hardware or when QubiC hardware is unavailable.

#### 3. Local Hardware Mode (`device_hardware.yaml`)

Executes directly on QubiC FPGA hardware:

```yaml
framework: qubic
target: superconducting_cnot
num_qubits: 3
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
from pathlib import Path
from self_service.frameworks.base import DeviceConfig
from self_service.server.config import Settings
from self_service.server.ir import NativeGateIR, GateOp, IRMetadata
from coda_qubic.framework import QubiCFramework

# Load device configuration
config = DeviceConfig.from_yaml("examples/device_sim.yaml")

# Validate configuration
framework = QubiCFramework()
errors = framework.validate_config(config)
if errors:
    raise ValueError(f"Configuration errors: {errors}")

# Create executor
settings = Settings()
executor = framework.create_executor(config, settings)

# Define a simple circuit
ir = NativeGateIR(
    num_qubits=3,
    target="superconducting_cnot",
    gates=[
        GateOp(gate="x90", qubits=[0], params=[]),
        GateOp(gate="cnot", qubits=[1, 0], params=[]),
    ],
    measurements=[0, 1, 2],
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

If using coda-self-service's automatic framework discovery:

```python
from self_service.server.executor import load_executor
from self_service.server.config import Settings
import os

# Set environment variable to device config
os.environ["CODA_DEVICE_CONFIG"] = "examples/device_sim.yaml"

# Load executor (automatically discovers QubiC framework)
settings = Settings()
executor = load_executor(settings)

# Execute circuits...
```

## Device Topology

The example `qubitcfg.json` defines an 8-qubit system (Q0-Q7), but the framework automatically selects the largest connected component with calibrated CNOT gates.

From the real hardware calibration, the largest connected component is:

```
Q1 -- Q2 -- Q3
```

This maps to logical qubits 0, 1, 2 respectively.

**Available directed CNOTs**:
- Control Q2 → Target Q1 (logical: 1 → 0)
- Control Q3 → Target Q2 (logical: 2 → 1)

The framework will use these gates for both `superconducting_cz` (via CZ = H-CNOT-H) and `superconducting_cnot` (native) IR targets.

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

See `qubitcfg.json` for a complete example with 8 qubits.
