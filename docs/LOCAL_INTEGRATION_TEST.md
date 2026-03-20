# Local Integration Test: VPN + QubiC Simulator

## Quick Start

```bash
CODA_DEVICE_CONFIG=./examples/device_sim.yaml \
uv run coda start --token <your-token>
```

This single command provisions the node against production, establishes
VPN connectivity, and starts consuming jobs -- executing them against
QubiC's built-in simulator instead of real hardware.

The runtime automatically:
- Connects to `https://coda.conductorquantum.com` (default `CODA_WEBAPP_URL`).
- Discovers `coda_qubic.executor_factory:create_executor` from the installed
  `coda-qubic` package (no need to set `CODA_EXECUTOR_FACTORY`).
- Uses the `CODA_DEVICE_CONFIG` path you provide (or `./site/device.yaml` by
  default if the file exists).

After the first successful connect, credentials are persisted to disk.
To reconnect (e.g. after a restart or network drop), run without
`--token`:

```bash
CODA_DEVICE_CONFIG=./examples/device_sim.yaml \
uv run coda start
```

No new token is needed. To wipe stored credentials and start fresh:

```bash
uv run coda reset
```

To skip the VPN tunnel for initial smoke testing, add
`CODA_VPN_REQUIRED=false`. Once you've confirmed the tunnel works,
remove that override (it defaults to `true`).

## How coda-qubic Integrates with coda-self-service

The `coda` CLI comes from `coda-self-service`. The two repos are wired
together at two levels:

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

### Executor factory

`coda-self-service` is completely framework-agnostic. It knows nothing
about QubiC, QUA, or any specific control system. At startup, it scans
installed packages for the convention
`<pkg>.executor_factory:create_executor` and uses the factory if
exactly one match is found. Since `coda-qubic` is installed, the
runtime discovers `coda_qubic.executor_factory:create_executor`
automatically.

You can also set it explicitly:

```
CODA_EXECUTOR_FACTORY=coda_qubic.executor_factory:create_executor
```

The factory receives the `Settings` object, reads
`settings.device_config` to find the YAML path, loads a `QubiCConfig`,
and assembles the full QubiC pipeline.

### Runtime: the `coda start` command

When you run `coda start --token <token>`:

1. The CLI (`cli.py`) pushes `--token` into `CODA_SELF_SERVICE_TOKEN`
   and starts uvicorn with `self_service.server.app:app`.
2. The FastAPI lifespan calls `connect_settings(settings)`, which POSTs
   the token to production and receives a bundle with JWT credentials,
   Redis URL, VPN profile, etc.
3. If VPN is required, the runtime writes the `.ovpn` profile to disk,
   launches an OpenVPN daemon, and polls until a TUN interface appears.
4. `load_executor(settings)` auto-discovers
   `coda_qubic.executor_factory:create_executor` (or uses
   `CODA_EXECUTOR_FACTORY` if set explicitly), and calls it with
   `settings`. The factory reads `CODA_DEVICE_CONFIG`, parses the
   YAML into a `QubiCConfig`, and builds a `QubiCJobRunner`.
5. The Redis consumer starts reading jobs from `qpu:<qpu_id>:jobs` and
   dispatching them to the executor.

## How the Backend Gets Selected

`build_executor()` in `coda_qubic.executor_factory` reads the
`runner_mode` and `use_sim` fields from `QubiCConfig`:

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

- **Simulator classifier file** — `examples/device_sim.yaml` points at the
  checked-in example classifier pickle. Treat it as a local smoke-test artifact
  only; for real hardware runs, use the classifier file or live-fit workflow
  supplied by the lab.
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
