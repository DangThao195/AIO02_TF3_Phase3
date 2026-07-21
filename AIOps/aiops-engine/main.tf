provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "ap-southeast-1"
}

variable "unique_suffix" {
  type    = string
  default = "techx-aiops"
}

# -------------------------------------------------------------
# 1. Amazon S3 Bucket để chứa Playbook
# -------------------------------------------------------------
resource "aws_s3_bucket" "playbook_bucket" {
  bucket        = "techx-aiops-playbooks-${var.unique_suffix}"
  force_destroy = true
}

resource "aws_s3_object" "playbook_file" {
  bucket = aws_s3_bucket.playbook_bucket.id
  key    = "playbooks/INCIDENT_HISTORY.md"
  source = "${path.module}/../phase3/onboarding/INCIDENT_HISTORY.md"
}

# -------------------------------------------------------------
# 2. IAM Role cấp quyền cho Amazon Bedrock KB
# -------------------------------------------------------------
resource "aws_iam_role" "bedrock_kb_role" {
  name = "AmazonBedrockExecutionRoleForKB-${var.unique_suffix}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "bedrock.amazonaws.com"
        }
        Action = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role_policy" "bedrock_kb_s3_policy" {
  name = "BedrockKBExecutionS3Policy"
  role = aws_iam_role.bedrock_kb_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.playbook_bucket.arn,
          "${aws_s3_bucket.playbook_bucket.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
        ]
      }
    ]
  })
}

# -------------------------------------------------------------
# 3. Amazon OpenSearch Serverless (Vector DB)
# -------------------------------------------------------------
resource "aws_opensearchserverless_security_policy" "encryption_policy" {
  name = "enc-${var.unique_suffix}"
  type = "encryption"
  policy = jsonencode({
    Rules = [
      {
        ResourceType = "collection"
        Resource     = ["collection/aiops-kb-${var.unique_suffix}"]
      }
    ]
    AWSOwnedKey = true
  })
}

resource "aws_opensearchserverless_security_policy" "network_policy" {
  name = "net-${var.unique_suffix}"
  type = "network"
  policy = jsonencode([
    {
      Rules = [
        {
          ResourceType = "collection"
          Resource     = ["collection/aiops-kb-${var.unique_suffix}"]
        },
        {
          ResourceType = "dashboard"
          Resource     = ["collection/aiops-kb-${var.unique_suffix}"]
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
          Resource     = ["collection/aiops-kb-${var.unique_suffix}"]
          Permission   = [
            "aoss:CreateCollectionItems",
            "aoss:DeleteCollectionItems",
            "aoss:UpdateCollectionItems",
            "aoss:DescribeCollectionItems"
          ]
        },
        {
          ResourceType = "index"
          Resource     = ["index/aiops-kb-${var.unique_suffix}/*"]
          Permission   = [
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
  name             = "aiops-kb-${var.unique_suffix}"
  type             = "VECTORSEARCH"
  description      = "Vector DB for AIOps Playbooks KB"
  depends_on       = [
    aws_opensearchserverless_security_policy.encryption_policy,
    aws_opensearchserverless_security_policy.network_policy,
    aws_opensearchserverless_access_policy.data_access_policy
  ]
}

resource "aws_iam_role_policy" "bedrock_kb_aoss_policy" {
  name = "BedrockKBExecutionAOSSPolicy"
  role = aws_iam_role.bedrock_kb_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "aoss:APIAccessAll"
        ]
        Resource = [
          aws_opensearchserverless_collection.vector_db.arn
        ]
      }
    ]
  })
}

# -------------------------------------------------------------
# 4. Amazon Bedrock Knowledge Base & Data Source
# -------------------------------------------------------------
resource "aws_bedrockagent_knowledge_base" "playbooks_kb" {
  name        = "aiops-playbooks-kb-${var.unique_suffix}"
  description = "Co so tri thuc chẩn đoán sự cố cho AIOps Engine"
  role_arn    = aws_iam_role.bedrock_kb_role.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
    }
  }

  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn    = aws_opensearchserverless_collection.vector_db.arn
      vector_index_name = "sre-playbooks-index"
      field_mapping {
        vector_field   = "vector"
        text_field     = "text"
        metadata_field = "meta"
      }
    }
  }
}

resource "aws_bedrockagent_data_source" "playbooks_ds" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.playbooks_kb.id
  name              = "s3-playbooks-${var.unique_suffix}"

  data_source_configuration {
    type = "S3"
    s3_data_source_configuration {
      bucket_arn        = aws_s3_bucket.playbook_bucket.arn
      inclusion_prefixes = ["playbooks/"]
    }
  }
}
