# coda-qubic

QubiC execution framework for coda-self-service.

Pipeline: **NativeGateIR → QubiC gate programs → hardware / simulator**.

## Quick Start — Connecting to a QubiC Lab

Step-by-step guide for integrating with an existing QubiC setup on-site. You
need three files from the lab: `qubitcfg.json`, `channel_config.json`, and a
GMM classifier pickle.

### 1. Prerequisites

```bash
brew install openvpn        # required — the node connects via VPN
```

Verify with `openvpn --version`. If you're on Linux, use your package manager
(`apt install openvpn`, etc.).

### 2. Install

```bash
git clone https://github.com/conductorquantum/coda-qubic.git
cd coda-qubic
uv sync --dev
./scripts/install-qubic-stack.sh
```

### 3. Copy calibration files from the lab

Place the lab's files in a working directory (e.g. `site/`):

```bash
mkdir site
# Copy these from the lab machine:
#   qubitcfg.json        — qubit calibration
#   channel_config.json  — FPGA channel mapping
#   classifier.pkl       — GMM readout classifier (if they have one)
```

### 4. Create a device YAML

Create `site/device.yaml` pointing at those files. All paths are resolved
relative to this YAML file, so `./qubitcfg.json` means "next to the YAML".

**RPC mode** (connecting to the lab's QubiC server — most common):

```yaml
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
target: superconducting_cnot
num_qubits: 3
calibration_path: ./qubitcfg.json
channel_config_path: ./channel_config.json
classifier_path: ./gmm_classifier_sim.pkl

runner_mode: local
use_sim: true
```

### 5. Validate the config

```bash
uv run python -c "
from coda_qubic.config import QubiCConfig

config = QubiCConfig.from_yaml('site/device.yaml')
print('OK —', config.target, config.num_qubits, 'qubits')
"
```

### 6. Run a test circuit

```bash
uv run python -c "
import asyncio
from self_service.server.ir import NativeGateIR, GateOp, IRMetadata
from coda_qubic.config import QubiCConfig
from coda_qubic.executor_factory import build_executor

config = QubiCConfig.from_yaml('site/device.yaml')
executor = build_executor(config)

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

### 7. Run via coda-self-service (full production path)

```bash
sudo uv run coda start --token <your-token>
```

`sudo` is required because OpenVPN needs root to create the tunnel interface.

The runtime automatically:
- Connects to `https://coda.conductorquantum.com` (the default `CODA_WEBAPP_URL`).
- Discovers `coda_qubic.executor_factory:create_executor` as the executor factory.
- Reads `./site/device.yaml` as the device config (the default `CODA_DEVICE_CONFIG` path).

After the first successful connect, credentials are persisted to disk.
To reconnect (e.g. after a restart, network drop, or reboot), just run
without `--token`:

```bash
sudo uv run coda start
```

No new token is needed -- the node authenticates with its stored JWT
credentials and resumes consuming jobs.

To wipe stored credentials and start fresh (requires a new token):

```bash
sudo uv run coda reset
```

To override any of the auto-detected settings:

```bash
sudo CODA_WEBAPP_URL=https://custom.example.com \
     CODA_EXECUTOR_FACTORY=coda_qubic.executor_factory:create_executor \
     CODA_DEVICE_CONFIG=./other/device.yaml \
     uv run coda start --token <your-token>
```

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
[`LBL-QubiC/software`](https://gitlab.com/LBL-QubiC/software),
[`LBL-QubiC/distributed_processor`](https://gitlab.com/LBL-QubiC/distributed_processor),
and [`coda-self-service`](https://github.com/conductorquantum/coda-self-service),
then installs them all editable (pulling `qubitconfig` and other deps from PyPI).

The checked-in example simulator classifier file is intended for local smoke
testing only. For real lab integration, use the classifier file or live-fit
workflow provided by the Berkeley team rather than trying to regenerate a local
simulator classifier.

Run integration tests:

```bash
uv run pytest tests/test_simulator_circuits.py tests/test_compile_integration.py
```

Requires Python 3.12+.

## Features

- **Device Derivation**: Derives device specs from `qubitcfg.json` via BFS over the calibrated connectivity graph
- **IR Translation**: Translates `NativeGateIR` circuits into QubiC gate-level programs
- **Multiple Backends**: RPC, local hardware (PLInterface), and simulation
- **Executor Factory**: Exposes `coda_qubic.executor_factory:create_executor` for use with `CODA_EXECUTOR_FACTORY`

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
from coda_qubic.config import QubiCConfig
from coda_qubic.executor_factory import build_executor

config = QubiCConfig.from_yaml("site/device.yaml")
executor = build_executor(config)
result = await executor.run(ir, shots=1000)
print(result.counts)
```

### Via coda-self-service

If `coda-qubic` is the only backend installed and `./site/device.yaml`
exists, all defaults are applied automatically:

```bash
uv run coda start --token <your-token>
```

To be explicit:

```bash
CODA_EXECUTOR_FACTORY=coda_qubic.executor_factory:create_executor \
CODA_DEVICE_CONFIG=./site/device.yaml \
uv run coda start --token <your-token>
```

## Architecture

```
src/coda_qubic/
├── __init__.py              # Package exports
├── config.py                # QubiCConfig (device YAML model)
├── device.py                # QubiCDeviceSpec derivation from qubitcfg.json
├── executor_factory.py      # CODA_EXECUTOR_FACTORY entry point
├── framework.py             # QubiCFramework convenience class
├── runner.py                # QubiCJobRunner (JobExecutor implementation)
├── support.py               # QubiC vendor dependency loading
└── translator.py            # NativeGateIR to QubiC gate translation
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

### Testing against staging

The staging environment at `https://staging.coda.conductorquantum.com` is
protected by Vercel Deployment Protection. Requests without valid credentials
receive a `401 Unauthorized` before they reach the app.

To bypass this, include the project's **automation bypass secret** via the
`CODA_SELF_SERVICE_CONNECT_HEADERS` environment variable:

```bash
CODA_WEBAPP_URL=https://staging.coda.conductorquantum.com \
CODA_DEVICE_CONFIG=./site/device.yaml \
CODA_SELF_SERVICE_AUTO_VPN=false \
CODA_VPN_REQUIRED=false \
CODA_SELF_SERVICE_CONNECT_HEADERS='{"x-vercel-protection-bypass": "<secret>"}' \
uv run coda start --token <your-staging-token>
```

| Variable | Purpose |
|---|---|
| `CODA_WEBAPP_URL` | Points the node at the staging deployment |
| `CODA_SELF_SERVICE_CONNECT_HEADERS` | JSON dict of extra headers sent with all outbound requests to the webapp (connect, heartbeat, VPN probes); must include the Vercel bypass header |
| `CODA_SELF_SERVICE_AUTO_VPN` / `CODA_VPN_REQUIRED` | Disable VPN for local testing where you don't need the tunnel |

**Where to find the bypass secret:** In the Vercel dashboard for the staging
project, go to **Settings → Deployment Protection → Protection Bypass for
Automation**. The secret is also available as the
`VERCEL_AUTOMATION_BYPASS_SECRET` environment variable inside Vercel
deployments.

## Configuration Reference

### Required Options

- `target`: IR target (`superconducting_cnot` or `superconducting_cz`)
- `num_qubits`: Number of qubits (must match derived device)
- `calibration_path`: Path to QubiC `qubitcfg.json`
- `channel_config_path`: Path to QubiC channel configuration JSON
- `classifier_path`: Path to GMM classifier for readout

### Runner Modes

| Mode | Config | Extra |
|---|---|---|
| RPC (default) | `runner_mode: rpc` | `rpc_host`, `rpc_port` (default 9095) |
| Local hardware | `runner_mode: local` | `xsa_commit` |
| Simulator | `runner_mode: local` + `use_sim: true` | — |

### Optional

- `qubic_root`: Path to QubiC vendor checkout (overrides `QUBIC_ROOT` env var)

## License

MIT
