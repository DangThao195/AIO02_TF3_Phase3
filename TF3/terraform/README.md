# TF3 — Bedrock Knowledge Base (SRE Playbooks) Terraform Blueprint

Ready-to-deploy blueprint for the RAG retrieval layer used by the AI Engine's
LLM Diagnostic module (`ai-engine/src/ai_engine/aiops/rca_assistant.py`).

## What it provisions

| # | Resource | Purpose |
|---|----------|---------|
| 1 | S3 bucket + object | Hosts `onboarding/INCIDENT_HISTORY.md` (8-incident SRE playbook corpus) under `playbooks/` |
| 2 | IAM role + 2 inline policies | Bedrock KB execution role: S3 read, `bedrock:InvokeModel` on Titan Embed v2, `aoss:APIAccessAll` |
| 3 | OpenSearch Serverless | Encryption / network / data-access policies + `VECTORSEARCH` collection |
| 4 | KNN vector index | `sre-playbooks-index` — dim 1024, hnsw/nmslib/cosinesimil (matches Titan Embed Text v2) |
| 5 | Bedrock Knowledge Base + S3 data source | Vector KB with field mapping `vector`/`text`/`meta` |

Provenance: ported from the Capstone03 reference (`aiops-engine/main.tf` +
`aiops-engine/scripts/deploy_bedrock_kb.py`). Improvements over the reference:
pinned provider versions, declarative vector-index creation (the reference
created it imperatively in Python), IAM-propagation wait, outputs, and
`etag`-driven re-upload when the playbook file changes.

## Deploy

The `opensearch` provider needs the collection endpoint, which only exists
after the collection is created — so the first apply is targeted:

```bash
terraform init
terraform apply -target=aws_opensearchserverless_collection.vector_db
terraform apply
```

Then start the first ingestion job (no native Terraform resource exists for
this step — the command is emitted as an output):

```bash
terraform output -raw ingestion_command
# aws bedrock-agent start-ingestion-job --knowledge-base-id ... --data-source-id ... --region ap-southeast-1
```

Re-run the ingestion command whenever `INCIDENT_HISTORY.md` changes (apply
first so the S3 object is re-uploaded).

## Wiring into the AI Engine

Set the output on the gateway:

```
KNOWLEDGE_BASE_ID=$(terraform output -raw knowledge_base_id)
```

The AI Engine queries the KB (`bedrock-agent-runtime retrieve`) to ground
incident diagnosis in the historical playbook — all retrieval stays inside
the `ai-engine` gateway; microservices are untouched (AI Gateway Pattern).

## Cost & security notes

- OpenSearch Serverless is the dominant cost (~2 OCU minimum when active).
  `terraform destroy` when not in use; `force_destroy` is set on the bucket
  and index so teardown is clean.
- Network policy is `AllowFromPublic` (dev posture, as in the reference).
  Switch to VPC endpoints before production use.
