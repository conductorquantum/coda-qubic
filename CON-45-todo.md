# CON-45: Self-Service QPUs — Berkeley

**Status:** Todo | **Priority:** Urgent | **Assignee:** Joel Pendleton

> User submits a circuit -> OpenQASM -> IR -> Execution on Berkeley Device using their control software

---

## Joel's Sub-Tickets

### Completed

- [x] **CON-46** — Understand & create interface for QubiC code and validate initial assumptions *(Done, completed 2026-03-13)*
  - Get Noah to answer questions in email chain
  - Determine if we need a config mapper from Berkeley QubiCs to stanza-private
  - Reference paper using QubiC with OpenQASM: [arxiv 2409.03725](https://arxiv.org/abs/2409.03725)

- [x] **CON-48** — Decouple BYOQ Fast-API service into standalone python package *(Done, completed 2026-03-17)*
  - Decouple into standalone package for use outside stanza-private
  - Create mock integrations for QubiC and OPX/QUA
  - Create Protocol for IR command set
  - Make publishable on PyIndex / open source (MIT License)
  - Support workflow_dispatch event trigger for releases
  - Ray took over and implemented: [coda-self-service](https://github.com/conductorquantum/coda-self-service)
  - PR: [stanza-private#32](https://github.com/conductorquantum/stanza-private/pull/32)

- [x] **CON-52** — Review: Add teams to Supabase *(Done, completed 2026-03-17)*

### Outstanding

- [ ] **CON-50** — Routine Tests *(Todo)*
  - [ ] **Single gate operation on a qubit** — Assert measured expectation value matches operation you send
  - [ ] **Universal gate test** — Assert that our universal gate set is a subset of their available gate set
  - [ ] **Testing correct ordering of gate operations**
    - [ ] Simple visual inspection comparing OpenQASM code directly to IR representation
    - [ ] Assert that the given OpenQASM circuit returns the human validated IR code
    - [ ] Circuit transpilation loop — Assert OpenQASM -> IR -> OpenQASM has no diff
    - [ ] Visual Inspection — OpenQASM circuit visualization matches IR generated figure
  - [ ] **Create superposition of multiple qubits (2 qubits)** — Assert approximate equal probability 50-50 over 1000 shots
  - [ ] **Single qubit randomized benchmark** — Assert +/- 5% of their calibration results
  - [ ] **2 qubit benchmark experiment** — Assert +/- 5% of their calibration results

- [ ] **CON-54** — Review: Infrastructure Tests *(Todo)*
