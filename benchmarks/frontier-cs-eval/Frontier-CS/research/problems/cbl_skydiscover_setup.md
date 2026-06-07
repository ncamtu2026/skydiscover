# CBL + CBL Multi — Skydiscover Integration Progress

## Variants chosen
- **CBL**: `mixed_availability_loose_deadline_small_overhead`
- **CBL Multi**: `high_availability_loose_deadline_small_overhead`

## Config settings (user-specified)
- `checkpoint_interval: 1`
- `api_base: https://api.deepseek.com/v1`
- model: `deepseek-v4-pro`, `reasoning_effort: "medium"`
- `log_level: "DEBUG"`
- `cascade_evaluation: true` (required for stage1/stage2)

## What has been done

### 1. Installed simulator packages (into project venv)
```bash
cd /home/osboxes/Desktop/skydiscover
uv pip install -e benchmarks/frontier-cs-eval/Frontier-CS/research/problems/cant_be_late/common/cant-be-late-simulator
uv pip install -e benchmarks/frontier-cs-eval/Frontier-CS/research/problems/cant_be_late_multi/common/cant-be-late-simulator
```

### 2. Extracted trace data
```bash
# CBL
tar -xzf .../cant_be_late/common/real_traces.tar.gz -C .../cant_be_late/common/cant-be-late-simulator/
# CBL Multi
tar -xzf .../cant_be_late_multi/common/real_traces.tar.gz -C .../cant_be_late_multi/common/cant-be-late-simulator/
```
Data landed at `cant-be-late-simulator/real/...` (CBL) and `cant-be-late-simulator/converted_multi_region_aligned/...` (multi).

### 3. Created data/ symlinks (evaluators expect `cant-be-late-simulator/data/...`)
```bash
# CBL: simulator expects data/real/ddl=search+task=48+overhead=0.02/real/{env}/...
ln -sfn .../cant-be-late-simulator/real  .../cant-be-late-simulator/data/real

# CBL Multi: simulator expects data/converted_multi_region_aligned/{region}/...
ln -sfn .../cant-be-late-simulator/converted_multi_region_aligned  .../cant-be-late-simulator/data/converted_multi_region_aligned
```

## What remains to do

### 4. Create evaluator_sd.py for CBL variant
**File**: `cant_be_late/mixed_availability_loose_deadline_small_overhead/evaluator_sd.py`

Logic:
- `evaluate_stage1(program_path)` → direct call to `cbl_evaluator.evaluate_stage1` (already single-arg)
- `evaluate_stage2(program_path)` → wraps `cbl_evaluator.evaluate_stage2` with:
  - `env_paths=ALL_REGIONS` (from `__init__.py`)
  - `job_configs=LOOSE_DEADLINE_CONFIG`
  - `changeover_delays=SMALL_OVERHEAD`
- Normalise `EvaluationResult` dataclass → dict if needed

### 5. Create evaluator_sd.py for CBL Multi variant
**File**: `cant_be_late_multi/high_availability_loose_deadline_small_overhead/evaluator_sd.py`

Logic:
- `evaluate_stage1(program_path)` → wraps `run_evaluator.evaluate_stage1` with:
  - `solution_path=Path(program_path)`
  - `data_path=str(SIM_ROOT / "data" / "converted_multi_region_aligned")`
  - `deadline_hours=LOOSE_DEADLINE` (48)
  - `restart_overhead_hours=SMALL_OVERHEAD` (0.05)
- `evaluate_stage2(program_path)` → wraps `run_evaluator.evaluate_stage2` with same + `scenarios=HIGH_AVAILABILITY_SCENARIOS`
- `SIM_ROOT` = `cant_be_late_multi/common/cant-be-late-simulator`

### 6. Create initial_program.py for CBL
**File**: `cant_be_late/mixed_availability_loose_deadline_small_overhead/initial_program.py`

Copy from `resources/programs/initial_greedy.py` (already in any variant's resources/).
Verify EVOLVE-BLOCK markers are present (CBL multi's version has them, CBL single does not — need to add).

### 7. Create config_deepseek.yaml for both
One config per problem (shared across variants):
- `cant_be_late/config_deepseek.yaml`
- `cant_be_late_multi/config_deepseek.yaml`

Must include `evaluator.cascade_evaluation: true`.
System message should explain the Strategy/_step interface.

### 8. Run commands
```bash
cd /home/osboxes/Desktop/skydiscover

# CBL
DEEPSEEK_API_KEY=sk-... uv run skydiscover-run \
  benchmarks/frontier-cs-eval/Frontier-CS/research/problems/cant_be_late/mixed_availability_loose_deadline_small_overhead/initial_program.py \
  benchmarks/frontier-cs-eval/Frontier-CS/research/problems/cant_be_late/mixed_availability_loose_deadline_small_overhead/evaluator_sd.py \
  -c benchmarks/frontier-cs-eval/Frontier-CS/research/problems/cant_be_late/config_deepseek.yaml \
  -s adaevolve -i 20

# CBL Multi
DEEPSEEK_API_KEY=sk-... uv run skydiscover-run \
  benchmarks/frontier-cs-eval/Frontier-CS/research/problems/cant_be_late_multi/high_availability_loose_deadline_small_overhead/resources/initial_program.py \
  benchmarks/frontier-cs-eval/Frontier-CS/research/problems/cant_be_late_multi/high_availability_loose_deadline_small_overhead/evaluator_sd.py \
  -c benchmarks/frontier-cs-eval/Frontier-CS/research/problems/cant_be_late_multi/config_deepseek.yaml \
  -s adaevolve -i 20
```

## Key paths reference
| Item | Path |
|---|---|
| CBL simulator | `cant_be_late/common/cant-be-late-simulator/` |
| CBL trace data | `cant-be-late-simulator/data/real/ddl=search+task=48+overhead=0.02/real/{env}/traces/random_start/*.json` |
| CBL common evaluator | `cant_be_late/common/cbl_evaluator.py` |
| CBL variant params | `cant_be_late/common/__init__.py` → `ALL_REGIONS`, `LOOSE_DEADLINE_CONFIG`, `SMALL_OVERHEAD` |
| Multi simulator | `cant_be_late_multi/common/cant-be-late-simulator/` |
| Multi trace data | `cant-be-late-simulator/data/converted_multi_region_aligned/{region}/{n}.json` |
| Multi common evaluator | `cant_be_late_multi/common/run_evaluator.py` |
| Multi variant params | `cant_be_late_multi/common/__init__.py` → `HIGH_AVAILABILITY_SCENARIOS`, `LOOSE_DEADLINE=48`, `SMALL_OVERHEAD=0.05` |
| Multi initial program | `cant_be_late_multi/high_availability_loose_deadline_small_overhead/resources/initial_program.py` |
