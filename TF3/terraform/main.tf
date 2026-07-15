# =====================================================================
# TF3 — AWS Bedrock Knowledge Base blueprint (SRE Playbooks / RAG)
# =====================================================================
# Provisions the retrieval layer used by the AI Engine's LLM Diagnostic
# module (rca_assistant): the enriched onboarding/INCIDENT_HISTORY.md is
# uploaded to S3, embedded with Titan Embed Text v2, and indexed in an
# OpenSearch Serverless vector collection behind a Bedrock Knowledge Base.
#
# Ported from the Capstone03 reference (aiops-engine/main.tf +
# scripts/deploy_bedrock_kb.py) with two gaps closed so the stack is
# deployable end-to-end from Terraform alone:
#   1. The KNN vector index (the reference created it imperatively via a
#      SigV4-signed request in deploy_bedrock_kb.py) is now declarative
#      through the opensearch provider.
#   2. Provider versions are pinned and outputs are defined.
# The only remaining post-apply step is starting the ingestion job — no
# native Terraform resource exists for it (see output "ingestion_command").
#
# NOTE: because the opensearch provider endpoint is only known after the
# collection exists, run a targeted apply first (see README.md):
#   terraform apply -target=aws_opensearchserverless_collection.vector_db
#   terraform apply

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    opensearch = {
      source  = "opensearch-project/opensearch"
      version = "~> 2.2"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.11"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Data-plane provider for the serverless collection (SigV4, service "aoss").
provider "opensearch" {
  url                   = aws_opensearchserverless_collection.vector_db.collection_endpoint
  aws_region            = var.aws_region
  aws_signature_service = "aoss"
  sign_aws_requests     = true
  healthcheck           = false
}

# ---------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------
variable "aws_region" {
  type    = string
  default = "ap-southeast-1"
}

variable "unique_suffix" {
  description = "Suffix appended to every resource name to avoid collisions between TF teams / environments."
  type        = string
  default     = "techx-tf3"
}

variable "incident_history_path" {
  description = "Path to the playbook markdown ingested into the KB. Defaults to the enriched phase3 onboarding incident history."
  type        = string
  default     = null
}

variable "vector_index_name" {
  type    = string
  default = "sre-playbooks-index"
}

locals {
  collection_name = "aiops-kb-${var.unique_suffix}"
  playbook_source = coalesce(var.incident_history_path, "${path.module}/../../onboarding/INCIDENT_HISTORY.md")

  # Titan Embed Text v2 → 1024-dimension vectors.
  embedding_model_arn = "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------
# 1. S3 bucket holding the SRE playbook corpus
# ---------------------------------------------------------------------
resource "aws_s3_bucket" "playbook_bucket" {
  bucket        = "techx-aiops-playbooks-${var.unique_suffix}"
  force_destroy = true
}

resource "aws_s3_object" "playbook_file" {
  bucket = aws_s3_bucket.playbook_bucket.id
  key    = "playbooks/INCIDENT_HISTORY.md"
  source = local.playbook_source
  etag   = filemd5(local.playbook_source)
}

# ---------------------------------------------------------------------
# 2. IAM execution role assumed by Bedrock KB
# ---------------------------------------------------------------------
resource "aws_iam_role" "bedrock_kb_role" {
  name = "AmazonBedrockExecutionRoleForKB-${var.unique_suffix}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "bedrock.amazonaws.com" }
        Action    = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "bedrock_kb_s3_policy" {
  name = "BedrockKBExecutionS3Policy"
  role = aws_iam_role.bedrock_kb_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.playbook_bucket.arn,
          "${aws_s3_bucket.playbook_bucket.arn}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = [local.embedding_model_arn]
      }
    ]
  })
}

resource "aws_iam_role_policy" "bedrock_kb_aoss_policy" {
  name = "BedrockKBExecutionAOSSPolicy"
  role = aws_iam_role.bedrock_kb_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["aoss:APIAccessAll"]
        Resource = [aws_opensearchserverless_collection.vector_db.arn]
      }
    ]
  })
}

# ---------------------------------------------------------------------
# 3. OpenSearch Serverless (vector store)
# ---------------------------------------------------------------------
resource "aws_opensearchserverless_security_policy" "encryption_policy" {
  name = "enc-${var.unique_suffix}"
  type = "encryption"
  policy = jsonencode({
    Rules = [
      {
        ResourceType = "collection"
        Resource     = ["collection/${local.collection_name}"]
      }
    ]
    AWSOwnedKey = true
  })
}

# Dev posture (matches reference): public network access. Tighten with
# VPC endpoints before any production use.
resource "aws_opensearchserverless_security_policy" "network_policy" {
  name = "net-${var.unique_suffix}"
  type = "network"
  policy = jsonencode([
    {
      Rules = [
        {
          ResourceType = "collection"
          Resource     = ["collection/${local.collection_name}"]
        },
        {
          ResourceType = "dashboard"
          Resource     = ["collection/${local.collection_name}"]
        }
      ]
      AllowFromPublic = true
    }
  ])
}

resource "aws_opensearchserverless_access_policy" "data_access_policy" {
  name = "data-${var.unique_suffix}"
  type = "data"
  policy = jsonencode([
    {
      Rules = [
        {
          ResourceType = "collection"
          Resource     = ["collection/${local.collection_name}"]
          Permission = [
            "aoss:CreateCollectionItems",
            "aoss:DeleteCollectionItems",
            "aoss:UpdateCollectionItems",
            "aoss:DescribeCollectionItems"
          ]
        },
        {
          ResourceType = "index"
          Resource     = ["index/${local.collection_name}/*"]
          Permission = [
            "aoss:CreateIndex",
            "aoss:DeleteIndex",
            "aoss:UpdateIndex",
            "aoss:DescribeIndex",
            "aoss:ReadDocument",
            "aoss:WriteDocument"
          ]
        }
      ]
      Principal = [
        aws_iam_role.bedrock_kb_role.arn,
        data.aws_caller_identity.current.arn
      ]
    }
  ])
}

resource "aws_opensearchserverless_collection" "vector_db" {
  name        = local.collection_name
  type        = "VECTORSEARCH"
  description = "Vector DB for AIOps SRE-playbooks Knowledge Base"

  depends_on = [
    aws_opensearchserverless_security_policy.encryption_policy,
    aws_opensearchserverless_security_policy.network_policy,
    aws_opensearchserverless_access_policy.data_access_policy
  ]
}

# Data-access policy + IAM changes take up to ~1 min to propagate before
# data-plane calls (index creation) succeed — same wait the reference
# script did with time.sleep().
resource "time_sleep" "aoss_iam_propagation" {
  create_duration = "60s"

  depends_on = [
    aws_opensearchserverless_collection.vector_db,
    aws_opensearchserverless_access_policy.data_access_policy,
    aws_iam_role_policy.bedrock_kb_aoss_policy
  ]
}

# ---------------------------------------------------------------------
# 4. KNN vector index (the piece the reference TF was missing — it only
#    existed in deploy_bedrock_kb.py). Mapping mirrors the script:
#    hnsw / nmslib / cosinesimil, dimension 1024 = Titan v2 output size.
# ---------------------------------------------------------------------
resource "opensearch_index" "sre_playbooks" {
  name          = var.vector_index_name
  index_knn     = true
  force_destroy = true

  mappings = jsonencode({
    properties = {
      id = { type = "keyword" }
      vector = {
        type      = "knn_vector"
        dimension = 1024
        method = {
          name       = "hnsw"
          engine     = "nmslib"
          space_type = "cosinesimil"
        }
      }
      text = { type = "text" }
      meta = { type = "text" }
    }
  })

  depends_on = [time_sleep.aoss_iam_propagation]
}

# ---------------------------------------------------------------------
# 5. Bedrock Knowledge Base + S3 data source
# ---------------------------------------------------------------------
resource "aws_bedrockagent_knowledge_base" "playbooks_kb" {
  name        = "aiops-playbooks-kb-${var.unique_suffix}"
  description = "Cơ sở tri thức chẩn đoán sự cố cho AIOps Engine (RAG grounding cho LLM Diagnostic)"
  role_arn    = aws_iam_role.bedrock_kb_role.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = local.embedding_model_arn
    }
  }

  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn    = aws_opensearchserverless_collection.vector_db.arn
      vector_index_name = var.vector_index_name
      field_mapping {
        vector_field   = "vector"
        text_field     = "text"
        metadata_field = "meta"
      }
    }
  }

  depends_on = [
    opensearch_index.sre_playbooks,
    aws_iam_role_policy.bedrock_kb_s3_policy,
    aws_iam_role_policy.bedrock_kb_aoss_policy
  ]
}

# After apply, sync/embed the corpus (no TF resource for ingestion jobs):
#   aws bedrock-agent start-ingestion-job \
#     --knowledge-base-id <knowledge_base_id> --data-source-id <data_source_id>
resource "aws_bedrockagent_data_source" "playbooks_ds" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.playbooks_kb.id
  name              = "s3-playbooks-${var.unique_suffix}"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn         = aws_s3_bucket.playbook_bucket.arn
      inclusion_prefixes = ["playbooks/"]
    }
  }
}

# ---------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------
output "knowledge_base_id" {
  description = "Set as KNOWLEDGE_BASE_ID for the AI Engine's rca_assistant / LLM Diagnostic module."
  value       = aws_bedrockagent_knowledge_base.playbooks_kb.id
}

output "data_source_id" {
  value = aws_bedrockagent_data_source.playbooks_ds.data_source_id
}

output "playbook_bucket" {
  value = aws_s3_bucket.playbook_bucket.id
}

output "collection_endpoint" {
  value = aws_opensearchserverless_collection.vector_db.collection_endpoint
}

output "ingestion_command" {
  description = "Run once after apply (and after every playbook update) to (re)embed the corpus."
  value       = "aws bedrock-agent start-ingestion-job --knowledge-base-id ${aws_bedrockagent_knowledge_base.playbooks_kb.id} --data-source-id ${aws_bedrockagent_data_source.playbooks_ds.data_source_id} --region ${var.aws_region}"
}
