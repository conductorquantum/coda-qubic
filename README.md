# coda-qubic

QubiC execution framework for coda-self-service.

This package extracts LBNL's QubiC hardware integration from stanza-private into a standalone, reusable framework that implements the `coda-self-service` pluggable architecture.

## Features

- **Framework Protocol Implementation**: Fully implements the `Framework` protocol from `coda-self-service`
- **Device Derivation**: Derives conservative device specifications from QubiC `qubitcfg.json` files using BFS over the calibrated connectivity graph
- **IR Translation**: Translates `NativeGateIR` circuits into QubiC gate-level programs
- **Multiple Execution Modes**: Supports RPC, local hardware (PLInterface), and simulation backends
- **Configurable Paths**: Makes QubiC vendor checkout paths configurable via `DeviceConfig`
- **Entry Point Registration**: Registers as `coda.frameworks.qubic` for automatic discovery

## Supported IR Targets

- `superconducting_cz` - Generic CZ-based IR, lowered via ZXZXZ decomposition and H-CNOT-H CZ synthesis
- `superconducting_cnot` - Native QubiC gates (x90, y_minus_90, virtual_z, cnot) passed through directly

## Installation

### From Source

```bash
git clone https://github.com/conductorquantum/coda-qubic.git
cd coda-qubic
uv sync --dev
```

### As a Dependency

Add to your `pyproject.toml`:

```toml
[project]
dependencies = [
    "coda-qubic @ git+https://github.com/conductorquantum/coda-qubic.git",
]
```

## Requirements

- Python 3.12+
- `coda-self-service` (installed automatically as editable dependency from `../coda-self-service`)
- QubiC vendor dependencies (optional, only required for actual hardware execution)

## Quick Start

See the `examples/` directory for complete working examples including:
- Real hardware calibration files (`qubitcfg.json`, `channel_config.json`)
- Device configuration templates for RPC, simulation, and hardware modes
- Example GMM classifier
- Detailed usage documentation

## Usage

### Device Configuration

Create a `device.yaml` file (see `examples/` for templates):

```yaml
framework: qubic
target: superconducting_cnot
num_qubits: 3
calibration_path: ./path/to/qubitcfg.json
channel_config_path: ./path/to/channel_config.json
classifier_path: ./path/to/gmm_classifier.json

# RPC mode (default)
runner_mode: rpc
rpc_host: qubic.local
rpc_port: 9734

# OR local hardware mode
# runner_mode: local
# xsa_commit: abc123def456

# OR simulation mode
# runner_mode: local
# use_sim: true

# Optional: specify QubiC vendor checkout location
# qubic_root: /path/to/qubic
```

### Programmatic Usage

```python
from pathlib import Path
from self_service.frameworks.base import DeviceConfig
from self_service.server.config import Settings
from coda_qubic.framework import QubiCFramework

# Load device configuration
config = DeviceConfig.from_yaml("device.yaml")

# Validate configuration
framework = QubiCFramework()
errors = framework.validate_config(config)
if errors:
    raise ValueError(f"Invalid config: {errors}")

# Create executor
settings = Settings()
executor = framework.create_executor(config, settings)

# Execute a circuit
from self_service.server.ir import NativeGateIR, GateOp, IRMetadata

ir = NativeGateIR(
    num_qubits=3,
    target="superconducting_cnot",
    gates=[
        GateOp(gate="x90", qubits=[0], params=[]),
        GateOp(gate="cnot", qubits=[1, 0], params=[]),
    ],
    measurements=[0, 1],
    metadata=IRMetadata(
        source_hash="test",
        compiled_at="2026-03-16T00:00:00Z",
    ),
)

result = await executor.run(ir, shots=1000)
print(result.counts)
```

### Via coda-self-service

Once installed, the framework is automatically discovered via the `coda.frameworks` entry point:

```python
from self_service.frameworks.registry import default_registry

registry = default_registry()
framework = registry.get("qubic")
```

## Architecture

### Module Structure

```
src/coda_qubic/
├── __init__.py          # Package exports
├── device.py            # QubiCDeviceSpec derivation from qubitcfg.json
├── support.py           # QubiC vendor dependency loading
├── translator.py        # NativeGateIR to QubiC gate translation
├── runner.py            # QubiCJobRunner (JobExecutor implementation)
└── framework.py         # QubiCFramework (Framework protocol)
```

### Key Components

- **QubiCDeviceSpec**: Parses `qubitcfg.json` and extracts the largest connected component of calibrated qubits
- **QubiCCircuitTranslator**: Lowers IR gates to QubiC's native instruction set
- **QubiCJobRunner**: Executes circuits via QubiC's `JobManager` and normalizes results
- **QubiCFramework**: Validates device configs and assembles the full execution pipeline

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/conductorquantum/coda-qubic.git
cd coda-qubic

# Install dependencies
uv sync --dev

# Run tests
uv run pytest

# Run linting
uv run ruff check .
uv run ruff format .

# Run type checking
uv run mypy src/coda_qubic
```

### Testing

The test suite includes:

- **Unit tests**: `test_device.py`, `test_translator.py`, `test_runner.py`, `test_framework.py`
- **Integration tests**: `test_compile_integration.py` (requires QubiC vendor checkout)

```bash
# Run all tests with coverage
uv run pytest --cov

# Run specific test file
uv run pytest tests/test_framework.py

# Run with verbose output
uv run pytest -v
```

Integration tests are automatically skipped if QubiC dependencies are unavailable.

### Code Quality

This project uses:

- **ruff**: Linting and formatting (configured in `pyproject.toml`)
- **mypy**: Strict type checking
- **pytest**: Testing with async support
- **pytest-cov**: Coverage reporting (target: 85%+)

## Configuration Options

### Required Options

- `calibration_path`: Path to QubiC `qubitcfg.json`
- `channel_config_path`: Path to QubiC channel configuration JSON
- `classifier_path`: Path to GMM classifier for readout

### Runner Modes

**RPC Mode** (default):
- `runner_mode: rpc`
- `rpc_host`: Hostname of QubiC RPC server
- `rpc_port`: Port of QubiC RPC server (default: 9734)

**Local Hardware Mode**:
- `runner_mode: local`
- `xsa_commit`: Commit hash for FPGA bitstream

**Simulation Mode**:
- `runner_mode: local`
- `use_sim: true`

### Optional Options

- `qubic_root`: Path to QubiC vendor checkout (overrides `QUBIC_ROOT` env var)

## Differences from stanza-private

This package adapts the QubiC integration from `stanza-private` with the following changes:

| Aspect | stanza-private | coda-qubic |
|--------|----------------|------------|
| Gate enum | `"y-90"` | `"y_minus_90"` |
| IR import | `stanza.server.ir` | `self_service.server.ir` |
| Return type | `JobResult` | `ExecutionResult` |
| Error type | `JobExecutionError` | `ExecutorError` |
| Configuration | Settings (env vars) | DeviceConfig (YAML) |
| QubiC paths | Hardcoded `repo_root()` | Configurable `qubic_root` |
| Factory method | `from_settings()` | `create_executor()` |

## License

MIT

## Contributing

Contributions are welcome! Please ensure:

1. All tests pass: `uv run pytest`
2. Code is formatted: `uv run ruff format .`
3. Linting passes: `uv run ruff check .`
4. Type checking passes: `uv run mypy src/coda_qubic`
5. Coverage remains above 85%

## Links

- [coda-self-service](https://github.com/conductorquantum/coda-self-service)
- [LBNL QubiC](https://qubic.lbl.gov/)
