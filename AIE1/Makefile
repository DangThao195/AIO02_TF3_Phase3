PYTHON ?= python
REPRO_DIR := repro
DATASET := $(REPRO_DIR)/datasets/dataset.jsonl
JUDGE_BENCHMARK := $(REPRO_DIR)/datasets/judge_benchmark.jsonl
ARTIFACT_DIR := $(REPRO_DIR)/artifacts
STAMP := $(shell $(PYTHON) -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))")

GRPC_ADDR ?= localhost:8085
GRPC_TIMEOUT_SECONDS ?= 60
JUDGE_PROVIDER ?= bedrock
JUDGE_MODEL ?= amazon.nova-micro-v1:0
JUDGE_REGION ?= us-east-1
CANDIDATE_PROVIDER ?= bedrock
CANDIDATE_MODEL ?= amazon.nova-lite-v1:0
MIN_SUITE_PASS_RATE ?= 0.80

.PHONY: eval-mandate14 eval-fidelity eval-guardrail-core eval-guardrail eval-hallucination eval-judge-agreement test-repro

test-repro:
	$(PYTHON) -m pytest $(REPRO_DIR)/test_eval_fidelity.py -q

eval-fidelity:
	$(PYTHON) $(REPRO_DIR)/eval_fidelity.py \
		--case-file $(DATASET) \
		--grpc-addr $(GRPC_ADDR) \
		--grpc-timeout-seconds $(GRPC_TIMEOUT_SECONDS) \
		--judge-provider $(JUDGE_PROVIDER) \
		--judge-model $(JUDGE_MODEL) \
		--judge-region $(JUDGE_REGION) \
		--judge-timeout-seconds $(GRPC_TIMEOUT_SECONDS) \
		--min-suite-pass-rate $(MIN_SUITE_PASS_RATE) \
		--strict \
		--out $(ARTIFACT_DIR)/fidelity_eval_mandate14_$(STAMP).json

eval-guardrail-core:
	$(PYTHON) $(REPRO_DIR)/run_eval_guardrail.py \
		--dataset $(DATASET) \
		--case-types normal,unanswerable,off_topic,injection_query,toxic_review \
		--grpc-addr $(GRPC_ADDR) \
		--grpc-timeout-seconds $(GRPC_TIMEOUT_SECONDS) \
		--candidate-provider $(CANDIDATE_PROVIDER) \
		--candidate-model $(CANDIDATE_MODEL) \
		--judge-provider $(JUDGE_PROVIDER) \
		--judge-model $(JUDGE_MODEL) \
		--expected-cases 197 \
		--strict \
		--out $(ARTIFACT_DIR)/dataset_runtime_mandate14_$(STAMP).json

eval-guardrail:
	$(PYTHON) $(REPRO_DIR)/run_eval_guardrail.py \
		--dataset $(DATASET) \
		--grpc-addr $(GRPC_ADDR) \
		--grpc-timeout-seconds $(GRPC_TIMEOUT_SECONDS) \
		--candidate-provider $(CANDIDATE_PROVIDER) \
		--candidate-model $(CANDIDATE_MODEL) \
		--judge-provider $(JUDGE_PROVIDER) \
		--judge-model $(JUDGE_MODEL) \
		--strict \
		--out $(ARTIFACT_DIR)/dataset_runtime_all_cases_$(STAMP).json

eval-hallucination:
	$(PYTHON) $(REPRO_DIR)/run_eval_guardrail.py \
		--dataset $(DATASET) \
		--case-types hallucination_probe \
		--expected-behaviors reject_unsupported \
		--grpc-addr $(GRPC_ADDR) \
		--grpc-timeout-seconds $(GRPC_TIMEOUT_SECONDS) \
		--candidate-provider $(CANDIDATE_PROVIDER) \
		--candidate-model $(CANDIDATE_MODEL) \
		--judge-provider $(JUDGE_PROVIDER) \
		--judge-model $(JUDGE_MODEL) \
		--expected-cases 3 \
		--min-products 1 \
		--strict \
		--out $(ARTIFACT_DIR)/hallucination_runtime_probe_$(STAMP).json

eval-judge-agreement:
	$(PYTHON) $(REPRO_DIR)/eval_support/judge_agreement.py \
		--dataset $(JUDGE_BENCHMARK) \
		--judge-provider $(JUDGE_PROVIDER) \
		--judge-model $(JUDGE_MODEL) \
		--judge-region $(JUDGE_REGION) \
		--judge-timeout-seconds $(GRPC_TIMEOUT_SECONDS) \
		--min-agreement-rate 0.80 \
		--strict \
		--out $(ARTIFACT_DIR)/judge_human_agreement_$(STAMP).json

eval-mandate14: test-repro eval-guardrail-core eval-fidelity eval-judge-agreement
