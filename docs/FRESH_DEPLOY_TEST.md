# Fresh-clone deployment test

A clean-room validation: clone the public repo into a new directory, build the venv, and deploy +
run the full lifecycle against a **brand-new workspace** that had never seen this project. The point
is to catch anything that only breaks on a first-time deploy.

## Environment

| | |
|---|---|
| Source | `git clone https://github.com/ronguerrero/lakebase-cicd-template-v2` → fresh dir |
| Workspace | `cenovus-qa` (a workspace with no prior `lakebase-app` project) |
| Project | `lakebase-app` (the template default — created from empty) |
| Python / deps | venv per README; `dash 4.4.1`, `databricks-sdk 0.145.0`, `psycopg 3.3.x` |
| Driven via | the guided console's `run_stage()` path (same code the Run buttons call) |

## Result

**PASS** (after one fix). All 10 stages reached `done`; the change `V004` promoted across the three
databases on the single `production` branch:

```
dev   app_dev_db  : V004, signup_source present
qa    app_qa_db   : V004, signup_source present
prod  app_prod_db : V004, signup_source present
tree  : ['production']        # ephemeral children created + cleaned up
```

Then rewound to the clean baseline (all three V003, `signup_source absent`) — demo-ready.

## Issues that arose, and the fix

| # | Severity | Symptom | Cause | Fix | Status |
|---|---|---|---|---|---|
| 1 | **Medium** | Stage 3 (`test-branch`) failed: `No module named pytest` | The console's "validate on the branch" stage runs `pytest`, but `demo/requirements.txt` didn't list it — a fresh clone that installs only that file has no pytest | Added `pytest>=8.0` to `demo/requirements.txt` | **Fixed** |
| 2 | Low (doc) | `pip install` installed into system Python, not the venv | The user's shell aliases `pip` to a system Python | README already prescribes `.venv/bin/python -m pip install …`; following it avoids this | Covered by README |
| 3 | Info | Fresh resolve pulled `databricks-sdk 0.145.0` (newer than the 0.144.0 previously verified) | `requirements` floor is `>=0.118.0` | Ran fine — the projects/branches **spec/status** model is unchanged across 0.139–0.145. No action; pin a ceiling only if a future SDK breaks it | Watch |
| 4 | Expected | `cenovus-qa` needed an interactive `databricks auth login` | Auth is per-user/session, never in the repo | Documented in README quickstart | Not a repo issue |

## What the test confirms

- **Provisioning a brand-new workspace works from empty**: `./ci/lakebase.sh init` created the
  project, the `production` branch, and all three databases; the baseline seeded cleanly. (The
  project half-deleted/undelete problem seen earlier was specific to *deleting* a project, not to a
  clean create — the create path is solid.)
- **Prior fixes hold on a fresh workspace** and did not recur: ≥3-char branch ids, `BranchSpec.ttl`
  as a protobuf `Duration`, Databricks Apps env in `app/src/app.yaml`, and the console running its
  subprocesses with the venv interpreter.
- **The only gap for a first-time cloner was the missing `pytest` dependency**, now fixed, so a
  clean `clone → venv → install → console` path runs green end to end.

## Reproduce

```bash
git clone https://github.com/ronguerrero/lakebase-cicd-template-v2 fresh && cd fresh
python3 -m venv .venv && .venv/bin/python -m pip install -r demo/requirements.txt
databricks auth login --profile <your-workspace>
DEMO_PROFILE=<your-workspace> DEMO_PROJECT=lakebase-app .venv/bin/python demo/console.py
# click Step 0, then walk the stages
```
