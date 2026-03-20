# coda-qubic

QubiC execution framework for coda-self-service.

Pipeline: **NativeGateIR → QubiC gate programs → hardware / simulator**.

## Quick Start — Connecting to a QubiC Lab

Step-by-step guide for integrating with an existing QubiC setup on-site. You
need three files from the lab: `qubitcfg.json`, `channel_config.json`, and a
GMM classifier pickle.

### 1. Install

```bash
git clone https://github.com/conductorquantum/coda-qubic.git
cd coda-qubic
uv sync --dev
./scripts/install-qubic-stack.sh
```

### 2. Copy calibration files from the lab

Place the lab's files in a working directory (e.g. `site/`):

```bash
mkdir site
# Copy these from the lab machine:
#   qubitcfg.json        — qubit calibration
#   channel_config.json  — FPGA channel mapping
#   classifier.pkl       — GMM readout classifier (if they have one)
```

### 3. Create a device YAML

Create `site/device.yaml` pointing at those files. All paths are resolved
relative to this YAML file, so `./qubitcfg.json` means "next to the YAML".

**RPC mode** (connecting to the lab's QubiC server — most common):

```yaml
framework: qubic
target: superconducting_cnot
num_qubits: 3                          # ask the lab
calibration_path: ./qubitcfg.json
channel_config_path: ./channel_config.json
classifier_path: ./classifier.pkl      # omit if fitting live

runner_mode: rpc
rpc_host: 192.168.1.120               # ask the lab
rpc_port: 9095                         # QubiC default; ask to confirm
```

**Simulator mode** (no hardware needed — good for testing the pipeline):

```yaml
framework: qubic
target: superconducting_cnot
num_qubits: 3
calibration_path: ./qubitcfg.json
channel_config_path: ./channel_config.json
classifier_path: ./gmm_classifier_sim.pkl

runner_mode: local
use_sim: true
```

### 4. Validate the config

```bash
uv run python -c "
from self_service.frameworks.base import DeviceConfig
from coda_qubic.framework import QubiCFramework

config = DeviceConfig.from_yaml('site/device.yaml')
errors = QubiCFramework().validate_config(config)
print('OK' if not errors else errors)
"
```

### 5. Run a test circuit

```bash
uv run python -c "
import asyncio
from unittest.mock import MagicMock
from self_service.frameworks.base import DeviceConfig
from self_service.server.ir import NativeGateIR, GateOp, IRMetadata
from coda_qubic.framework import QubiCFramework

config = DeviceConfig.from_yaml('site/device.yaml')
executor = QubiCFramework().create_executor(config, MagicMock())

ir = NativeGateIR(
    num_qubits=3,
    target='superconducting_cnot',
    gates=[GateOp(gate='x90', qubits=[0], params=[])],
    measurements=[0, 1, 2],
    metadata=IRMetadata(source_hash='test', compiled_at='2026-03-23T00:00:00Z'),
)

result = asyncio.run(executor.run(ir, shots=100))
print(result.counts)
"
```

### 6. Run via coda-self-service (full production path)

```bash
CODA_DEVICE_CONFIG=./site/device.yaml uv run coda start --token <your-token>
```

This starts the full job loop: VPN, Redis consumer, and QubiC executor.

### Things to ask the lab

| What | Why |
|---|---|
| RPC host IP and port | Connection target |
| `qubitcfg.json` + `channel_config.json` | Compilation and device derivation |
| Number of calibrated qubits and connectivity | `num_qubits` in YAML must match |
| GMM classifier file (or "we fit live") | Readout discrimination |
| QubiC software version/branch | API compatibility |
| Single-board or multi-board setup | Determines which RPC server is running |

See [`docs/berkeley-visit-checklist.md`](docs/berkeley-visit-checklist.md) for
the full list of open questions and failure modes.

---

## Installation

```bash
git clone https://github.com/conductorquantum/coda-qubic.git
cd coda-qubic
uv sync --dev
./scripts/install-qubic-stack.sh   # clones QubiC + distproc into .qubic-stack/
```

The install script shallow-clones
[`LBL-QubiC/software`](https://gitlab.com/LBL-QubiC/software) and
[`LBL-QubiC/distributed_processor`](https://gitlab.com/LBL-QubiC/distributed_processor),
then installs them editable (pulling `qubitconfig` and other deps from PyPI).

Regenerate the simulator GMM pickle after stack upgrades:

```bash
uv run python scripts/build-example-gmm-pickle.py
```

Run integration tests:

```bash
uv run pytest tests/test_simulator_circuits.py tests/test_compile_integration.py
```

Requires Python 3.12+ and `coda-self-service` (installed automatically as an
editable sibling dependency).

## Features

- **Framework Protocol**: Implements the `Framework` protocol from `coda-self-service`
- **Device Derivation**: Derives device specs from `qubitcfg.json` via BFS over the calibrated connectivity graph
- **IR Translation**: Translates `NativeGateIR` circuits into QubiC gate-level programs
- **Multiple Backends**: RPC, local hardware (PLInterface), and simulation
- **Entry Point Registration**: Registers as `coda.frameworks.qubic` for automatic discovery

## Supported IR Targets

- `superconducting_cz` — Generic CZ-based IR, lowered via ZXZXZ decomposition and H-CNOT-H CZ synthesis
- `superconducting_cnot` — Native QubiC gates (x90, y_minus_90, virtual_z, cnot) passed through directly

## Usage

### Device Configuration

See `examples/` for complete templates:
- `device_rpc.yaml` — RPC mode (remote QubiC server)
- `device_sim.yaml` — Simulator mode (no hardware)
- `device_hardware.yaml` — Local hardware mode (direct FPGA)

All file paths in the YAML (`calibration_path`, `channel_config_path`,
`classifier_path`, `qubic_root`) are resolved relative to the YAML file's
directory, not the working directory.

### Programmatic Usage

```python
from self_service.frameworks.base import DeviceConfig
from coda_qubic.framework import QubiCFramework

config = DeviceConfig.from_yaml("site/device.yaml")
framework = QubiCFramework()
errors = framework.validate_config(config)
if errors:
    raise ValueError(f"Invalid config: {errors}")

executor = framework.create_executor(config, settings)
result = await executor.run(ir, shots=1000)
print(result.counts)
```

### Via coda-self-service

The framework is automatically discovered via the `coda.frameworks` entry point:

```python
from self_service.frameworks.registry import default_registry

registry = default_registry()
framework = registry.get("qubic")
```

## Architecture

```
src/coda_qubic/
├── __init__.py          # Package exports
├── device.py            # QubiCDeviceSpec derivation from qubitcfg.json
├── support.py           # QubiC vendor dependency loading
├── translator.py        # NativeGateIR to QubiC gate translation
├── runner.py            # QubiCJobRunner (JobExecutor implementation)
└── framework.py         # QubiCFramework (Framework protocol)
```

## Development

```bash
uv run pytest              # run all tests
uv run pytest --cov        # with coverage
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy src/coda_qubic # type check
```

Integration tests are automatically skipped if QubiC dependencies are unavailable.

## Configuration Reference

### Required Options

- `calibration_path`: Path to QubiC `qubitcfg.json`
- `channel_config_path`: Path to QubiC channel configuration JSON
- `classifier_path`: Path to GMM classifier for readout

### Runner Modes

| Mode | Config | Extra |
|---|---|---|
| RPC (default) | `runner_mode: rpc` | `rpc_host`, `rpc_port` (default 9734) |
| Local hardware | `runner_mode: local` | `xsa_commit` |
| Simulator | `runner_mode: local` + `use_sim: true` | — |

### Optional

- `qubic_root`: Path to QubiC vendor checkout (overrides `QUBIC_ROOT` env var)

## License

MIT
