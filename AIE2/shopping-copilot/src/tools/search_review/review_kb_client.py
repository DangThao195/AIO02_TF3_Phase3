import os
import re
import boto3
from typing import List, Optional, Dict


class BedrockReviewRAGStrategy:
    """
    Query AWS Bedrock Knowledge Base to retrieve reviews for products.
    Targets specifically the PRODUCT REVIEWS data source (REVIEWS_DATA_SOURCE_ID).
    """

    @property
    def kb_id(self) -> Optional[str]:
        return os.environ.get("BEDROCK_KB_ID")

    @property
    def review_data_source_id(self) -> Optional[str]:
        """ID of the productreview datasource in Bedrock KB."""
        return os.environ.get("REVIEWS_DATA_SOURCE_ID", "M2YA7L7GEA")

    @property
    def region(self) -> str:
        return os.environ.get("BEDROCK_KB_REGION", "us-east-1")

    def retrieve_reviews(self, product_id: str) -> List[Dict]:
        """
        Query Bedrock KB specifically filtering the Product Review Datasource (REVIEWS_DATA_SOURCE_ID).
        Parses review format:
          Product ID: <id>
          Product Reviews (N total):
            - id: 1 | username: X | description: Y | score: Z
        Returns list of dicts: [{username, score, description}]
        """
        kb_id = self.kb_id
        if not kb_id:
            return []

        ds_id = self.review_data_source_id

        try:
            session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE"))
            client = session.client("bedrock-agent-runtime", region_name=self.region)

            retrieval_config = {
                "vectorSearchConfiguration": {"numberOfResults": 5}
            }

            # Filter strictly by PRODUCT REVIEW data source ID
            if ds_id:
                retrieval_config["vectorSearchConfiguration"]["filter"] = {
                    "equals": {
                        "key": "x-amz-bedrock-kb-data-source-id",
                        "value": ds_id
                    }
                }

            response = client.retrieve(
                knowledgeBaseId=kb_id,
                retrievalQuery={"text": f"product reviews {product_id}"},
                retrievalConfiguration=retrieval_config
            )

            reviews = []
            for res in response.get("retrievalResults", []):
                text = res.get("content", {}).get("text", "")

                # Only process chunks that belong to this product_id
                if product_id.upper() not in text.upper():
                    continue

                for line in text.splitlines():
                    line = line.strip().lstrip("- ")
                    if "username:" not in line.lower():
                        continue
                    parts = {}
                    for segment in line.split(" | "):
                        if ":" in segment:
                            k, _, v = segment.partition(":")
                            parts[k.strip().lower()] = v.strip()
                    if "username" in parts:
                        try:
                            score = float(parts.get("score", 0))
                        except ValueError:
                            score = 0.0
                        reviews.append({
                            "username": parts.get("username", "Anonymous"),
                            "score": score,
                            "description": parts.get("description", ""),
                        })

            print(f"[REVIEW RAG] retrieve_reviews({product_id}): found {len(reviews)} reviews from Review KB DS ({ds_id})")
            return reviews

        except Exception as e:
            print(f"[REVIEW RAG] retrieve_reviews error: {e}")
            return []
