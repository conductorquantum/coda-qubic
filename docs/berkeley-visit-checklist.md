# Berkeley On-Site Integration Checklist

Campbell Hall, UC Berkeley — 23 March 2026

## Pre-Visit Email Requests

If any of these can be obtained before the visit, it will save significant
time on-site:

1. A sample `qubitcfg.json` (structure only is fine — we need key names, not
   calibration values)
2. A sample `channel_config.json`
3. The QubiC software version/branch in use
4. The RPC server port and startup method
5. The current qubit count and connectivity graph
6. Whether they use a pre-fitted GMM pickle or fit the classifier live

---

## Open Questions — Ranked by Risk

### Critical (will stop us if wrong)

#### 1. RPC server port mismatch

Our `QubiCConfig` defaults to port **9734** when `rpc_port` is omitted from
the device YAML, but QubiC's own `CircuitRunnerClient` and server config both
default to **9095**. If they run the stock server and we omit `rpc_port`,
connection will silently fail.

**Ask:** What port does your RPC server run on? Is it the stock
`soc_rpc_server` on 9095, or a job-level server on a different port?

#### 2. Which QubiC server entry point do they use?

QubiC has two server modes: a low-level `soc_rpc_server` (single board,
exposes `run_circuit_batch` directly) and a higher-level `job_rpc_server` /
`JobServer` (multi-board sync, different RPC surface). Our
`CircuitRunnerClient` calls the low-level one. If they run the job server, the
RPC interface is different.

**Ask:** Do you start QubiC with `soc_rpc_server` or the multi-board
`job_rpc_server`? Are there any wrapper scripts?

#### 3. qubitcfg.json structure and qubit naming

Our device derivation hard-codes `^Q(\d+)$` as the qubit regex and
`^Q(\d+)Q(\d+)CR$` for cross-resonance gates. If their calibration file uses
different names (`QB0`, `q0`, or numbered differently), device parsing fails
silently — qubits are skipped and the device spec comes out empty or wrong.

**Ask:** Can we get a copy of your current `qubitcfg.json` and
`channel_config.json` ahead of time (even redacted calibration values are
fine — we just need the key structure)?

#### 4. Gate naming in QChip

Our translator emits `{"name": "X90", ...}`, `{"name": "Y-90", ...}`,
`{"name": "CNOT", ...}`. The QubiC compiler resolves these by concatenating
`qubit + name` (e.g. `Q0X90`) and looking that up in the QChip. If their
calibration file uses different gate names (`x90`, `X-90`, `Xp`, `CR` instead
of `CNOT`), compilation fails with a missing-gate error.

**Ask:** What gate names does your QChip define? Specifically: single-qubit
rotations, CNOT/CR, and readout?

---

### High (will produce wrong results or crash mid-run)

#### 5. Classifier format and live calibration

QubiC `JobManager` treats a string `gmm_manager` as a pickle path
(`pkl.load`). But their lab likely doesn't use a pre-baked pickle — their own
test code always creates an empty `GMMManager` and fits it live with
`fit_gmm=True`. If we hand them a stale pickle that doesn't match their
current IQ blobs, readout classification will be wrong and every bitstring
result will be garbage.

Related local limitation: the current upstream `SimInterface` in our cloned
QubiC stack returns state-independent synthetic readout data, so the example
simulator pickle cannot be trusted as a quantitative proxy for real lab IQ
discrimination.

**Ask:** Do you load a pre-fitted GMM classifier from disk, or do you fit it
live at the start of each session? If from disk, pickle or JSON? If live, how
many calibration shots do you typically use?

#### 6. channel_config.json compatibility

The entire compilation and assembly pipeline depends on `channel_config.json`
having the right structure: `fpga_clk_freq` at the top level, channels named
`Q{n}.qdrv`, `Q{n}.rdrv`, `Q{n}.rdlo`, each with `core_ind`, `elem_ind`,
`elem_type`, `elem_params`, and `acc_mem_name` on readout channels. A mismatch
in any of these breaks assembly or GMM channel mapping.

**Ask:** Can we use the `channel_config.json` from your current setup, or does
it need to be regenerated for each cooldown?

#### 7. `reads_per_shot` assumption

Our runner hardcodes `reads_per_shot=1`. QubiC supports multiple reads per
shot (mid-circuit measurement). If their workflow uses >1 reads per shot,
`_coerce_count_value` will raise because it expects length-1 arrays.

**Ask:** Do your typical circuits use a single readout at the end, or do you
do mid-circuit measurements with multiple reads per shot?

---

### Medium (will cause subtle issues or require on-the-fly patching)

#### 8. QubiC software version drift

We cloned `master` from both `LBL-QubiC/software` and
`distributed_processor`. If Berkeley runs a different branch or a pinned older
version, there could be API differences in `JobManager`, `CircuitRunner`,
`FPGAConfig`, or the compiler/assembler stages.

**Ask:** Which version/branch/tag of the QubiC software and
distributed_processor are you running? Is it `master`, or a tagged release
like `25.05` or `25.08`?

#### 9. FPGA configuration (clock, cores, nyquist zone)

`FPGAConfig()` is constructed with no arguments in our code (uses defaults:
2 ns clock period, 16 cores). Their actual hardware may have different
settings. The server config they use includes `adc_nyquist_zone`,
`dac_nyquist_zone`, `lmk_freq` — none of which we set.

**Ask:** Do we need to pass any custom parameters to `FPGAConfig`? What's your
FPGA clock frequency and ADC/DAC nyquist zone configuration?

#### 10. Qubit count and connectivity

Our example config says `num_qubits: 3` with connectivity `CNOT(2,1)` and
`CNOT(1,0)`. Their actual device may have more qubits and different
connectivity. Our device derivation picks the largest connected component, but
if `num_qubits` in the YAML doesn't match, `create_executor` will raise.

**Ask:** How many qubits are currently calibrated and connected? What's the
connectivity graph (which directed CNOT/CR edges exist)?

#### 11. Result qubit ordering

`CircuitCounts` sorts qubits lexicographically (`sorted(shot_dict.keys())`),
and our `_normalize_counts` reorders to match `measurement_hardware_order`. If
QubiC returns readout data for qubits that weren't explicitly measured (e.g.
spectator qubits that got read out), the assertion will raise.

**Ask:** Does the system ever return readout data for qubits that weren't
explicitly measured in the circuit?

---

### Low (good to know but unlikely to block)

#### 12. OpenQASM status

Ke's email (16 March) said they don't currently support OpenQASM and are
migrating codebases. Our pipeline goes OpenQASM → NativeIR → QubiC gate-level,
so we don't depend on their OpenQASM support. But worth confirming nothing
changed.

**Ask:** Has the OpenQASM/Qiskit compilation path been restored in your
current codebase, or is everything still gate-level/pulse-level only?

#### 13. Network topology at Campbell Hall

RPC uses XML-RPC over HTTP. We need network access from our laptop to the RPC
server IP (likely `192.168.x.x` per their config).

**Ask:** Will we be on the same network as the QubiC RPC server? Do we need
any VPN, SSH tunnel, or firewall rules?

#### 14. Multi-board / synchronization

Their `jobserver_config.yaml` shows a multi-board setup (boards named
`huracan` and `sian`). If they use the multi-board job server, the RPC
interface is different from the single-board `soc_rpc_server`.

**Ask:** Are we targeting a single-board or multi-board configuration?

---

## Potential Failure Modes — Quick Reference

| Area | Our Assumption | What Breaks |
|---|---|---|
| RPC | Port 9734 | Connection fails if server uses 9095 |
| RPC | `soc_rpc_server` (single board) | Wrong RPC surface if they run `job_rpc_server` |
| Circuit | Gate names `X90`, `Y-90`, `CNOT` | Compiler fails if QChip uses different names |
| qubitcfg | `Qubits` and `Gates` top-level keys | Parse error if structure differs |
| qubitcfg | `freq`, `readfreq` per qubit | Qubits silently skipped if missing |
| qubitcfg | `Q{n}` naming pattern | Device derivation fails for other names |
| qubitcfg | `Q{a}Q{b}CR` / `Q{a}Q{b}CNOT` | No 2Q gates if naming differs |
| channel_config | `fpga_clk_freq` present | `load_channel_configs` fails |
| channel_config | `Q{n}.qdrv/.rdrv/.rdlo` | Assembly and GMM mapping break |
| GMM | Channel → qubit via `split('.')[0]` | Wrong mapping if channel names differ |
| GMM | Pre-fitted pickle matches live IQ | Garbage readout if IQ blobs shifted |
| Simulator | Synthetic IQ is state-dependent | Local simulator classifier is meaningless if `SimInterface` returns fixed clouds |
| Runner | `reads_per_shot=1` | Error for mid-circuit measurement |
| Results | `CircuitCounts.qubits` sorted | Bit order wrong if result format differs |
| FPGAConfig | Default 2 ns clock, 16 cores | Timing/compilation wrong if hardware differs |
| Version | `master` branch | API mismatch if they run older/different branch |

---

## What We Have Working Today

- OpenQASM → NativeIR → QubiC gate-level translation (both `superconducting_cnot`
  and `superconducting_cz` targets)
- Full compile + assemble pipeline tested against QubiC `master`
- Simulator integration tests (GHZ, Hadamard, QFT, Grover circuits) for
  pipeline smoke coverage only, not quantitative readout fidelity
- Path resolution for all config files (relative to YAML, not cwd)
- Lazy `PLInterface` import (simulator/RPC work without `pynq`)
- Install script for QubiC vendor stack
- CI job that clones + installs QubiC and runs integration tests

## What We Cannot Test Until On-Site

- Actual RPC connectivity to their server
- Compilation against their real `qubitcfg.json` / `channel_config.json`
- GMM classifier fitting on real IQ data
- Whether their live readout IQ blobs and classifier workflow match our
  assumptions (pickle vs live fit, label ordering, channel naming)
- Hardware execution and result parsing
- Network access and latency
