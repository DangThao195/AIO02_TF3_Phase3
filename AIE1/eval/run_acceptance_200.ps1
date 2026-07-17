<#
.SYNOPSIS
  Run the mandated 200-case, multi-product runtime acceptance suite.

The candidate and judge defaults are deliberately different Bedrock models.  Pass
`-EnableToxicDbE2E` only with an isolated test database: the runner inserts and
deletes synthetic reviews for toxic-review cases.
#>
param(
  [string]$GrpcAddr = $(if ($env:PRODUCT_REVIEWS_ADDR) { $env:PRODUCT_REVIEWS_ADDR } else { "localhost:8085" }),
  [string]$Dataset = (Join-Path $PSScriptRoot "dataset.jsonl"),
  [string]$Out = (Join-Path (Join-Path $PSScriptRoot "..\repro\artifacts") "dataset_runtime_e2e_acceptance_200.json"),
  [string]$CandidateModel = $(if ($env:LLM_MODEL) { $env:LLM_MODEL } else { "amazon.nova-micro-v1:0" }),
  [string]$JudgeModel = $(if ($env:JUDGE_MODEL) { $env:JUDGE_MODEL } else { "amazon.nova-lite-v1:0" }),
  [string]$UsageLog = "",
  [switch]$EnableToxicDbE2E,
  [switch]$Strict
)

$arguments = @(
  (Join-Path $PSScriptRoot "run_eval.py"),
  "--dataset", $Dataset,
  "--grpc-addr", $GrpcAddr,
  "--expected-cases", "200",
  "--min-products", "5",
  "--candidate-provider", "bedrock",
  "--candidate-model", $CandidateModel,
  "--judge-provider", "bedrock",
  "--judge-model", $JudgeModel,
  "--out", $Out
)
if ($UsageLog) { $arguments += @("--usage-log", $UsageLog) }
if ($EnableToxicDbE2E) { $arguments += "--enable-toxic-db-e2e" }
if ($Strict) { $arguments += "--strict" }

python @arguments
exit $LASTEXITCODE
