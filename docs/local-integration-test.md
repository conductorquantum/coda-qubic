# Local Integration Test: VPN + QubiC Simulator

## Quick Start

```bash
CODA_DEVICE_CONFIG=./examples/device_sim.yaml \
uv run coda start --token <your-token>
```

This single command provisions the node against production, establishes
VPN connectivity, and starts consuming jobs — executing them against
QubiC's built-in simulator instead of real hardware.

To skip the VPN tunnel for initial smoke testing, add
`CODA_VPN_REQUIRED=false`. Once you've confirmed the tunnel works,
remove that override (it defaults to `true`).

## How coda-qubic Integrates with coda-self-service

The `coda` CLI comes from `coda-self-service`. The two repos are wired
together at three levels:

### Dependency

`coda-qubic` declares `coda-self-service` as an editable path
dependency in `pyproject.toml`:

```toml
[tool.uv.sources]
coda-self-service = { path = "coda-self-service", editable = true }
```

So when you `uv sync` in `coda-qubic`, both packages are installed into
the same environment. The `coda` command is a console script registered
by `coda-self-service`:

```toml
# coda-self-service/pyproject.toml
[project.scripts]
coda = "self_service.server.cli:main"
```

### Entry-point discovery

`coda-qubic` registers itself as a framework via a Python entry point:

```toml
# pyproject.toml (coda-qubic)
[project.entry-points."coda.frameworks"]
qubic = "coda_qubic.framework:QubiCFramework"
```

When `coda-self-service` needs to create an executor from a device
config, its `FrameworkRegistry` discovers installed frameworks through
`importlib.metadata.entry_points(group="coda.frameworks")`. This is how
`coda-self-service` finds `QubiCFramework` without any hardcoded import.

### Runtime: the `coda start` command

When you run `coda start --token <token>`:

1. The CLI (`cli.py`) pushes `--token` into `CODA_SELF_SERVICE_TOKEN`
   and starts uvicorn with `self_service.server.app:app`.
2. The FastAPI lifespan calls `connect_settings(settings)`, which POSTs
   the token to production and receives a bundle with JWT credentials,
   Redis URL, VPN profile, etc.
3. If VPN is required, the runtime writes the `.ovpn` profile to disk,
   launches an OpenVPN daemon, and polls until a TUN interface appears.
4. `load_executor(settings)` sees `CODA_DEVICE_CONFIG` is set, parses
   the YAML, auto-detects the QubiC framework via the entry point, and
   calls `QubiCFramework.create_executor()`.
5. The Redis consumer starts reading jobs from `qpu:<qpu_id>:jobs` and
   dispatching them to the executor.

## How the Backend Gets Selected

`QubiCFramework.create_executor()` calls `_build_circuit_runner`, which
branches on the YAML fields `runner_mode` and `use_sim`:

| `runner_mode` | `use_sim` | Backend |
|---|---|---|
| `rpc` | — | `CircuitRunnerClient(host, port)` — remote QubiC RPC server |
| `local` | `true` | `CircuitRunner(SimInterface())` — QubiC's built-in simulator |
| `local` | `false` | `CircuitRunner(PLInterface(commit_hash=...))` — direct FPGA hardware |

With `examples/device_sim.yaml` (`runner_mode: local`, `use_sim: true`),
the simulator backend is selected. The rest of the runtime — VPN,
Redis, JWT auth, webhooks — works identically to a real hardware
deployment.

## Prerequisites

- **QubiC vendor stack** — from the repo root run:

  ```bash
  ./scripts/install-qubic-stack.sh
  ```

  This shallow-clones LBNL `software` and `distributed_processor` under
  `./.qubic-stack` and installs them editable via `uv pip install -e …`.
  Optionally set `QUBIC_ROOT` to that tree, or add `qubic_root:` to the
  device YAML (usually unnecessary once editable installs are present).

- **Simulator classifier file** — `examples/device_sim.yaml` points at
  `gmm_classifier_sim.pkl` (QubiC loads string paths as pickle). Regenerate
  with `uv run python scripts/build-example-gmm-pickle.py` after updating
  the QubiC stack if needed.
- **OpenVPN** must be on `$PATH` if VPN is required.
- The **prod-registered QPU metadata** (`num_qubits`, `native_gate_set`)
  must be compatible with the simulator device config. The example
  config derives a 3-qubit device (Q1–Q3) with `superconducting_cnot`.

## Verifying VPN Only

To check VPN connectivity without starting the full job loop:

```bash
CODA_SELF_SERVICE_TOKEN=<your-token> uv run coda doctor
```

This prints a diagnostic summary: endpoints, executor, VPN interface,
and OpenVPN status.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `VPN preflight failed` | Check that OpenVPN is installed and the token hasn't been consumed already. Run `coda doctor` for details. |
| `QubiC dependencies are unavailable` | Set `QUBIC_ROOT` or add `qubic_root: /path/to/qubic` to the device YAML. |
| `num_qubits does not match QubiC device size` | The YAML says `num_qubits: 3` but the `qubitcfg.json` derived a different count. Update the YAML to match. |
| `No framework supports target` | If using `superconducting_cz`, add `framework: qubic` explicitly (QUA also supports that target). |
