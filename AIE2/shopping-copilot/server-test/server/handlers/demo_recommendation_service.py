import random

from server import demo_pb2 as pb
from server import demo_pb2_grpc as grpc_svc
from server import db


class DemoRecommendationService(grpc_svc.RecommendationServiceServicer):

    async def ListRecommendations(self, request, context):
        exclude = set(request.product_ids)
        rows = await db.fetch("SELECT id FROM products")
        all_ids = [r["id"] for r in rows if r["id"] not in exclude]
        selected = random.sample(all_ids, min(5, len(all_ids)))
        return pb.ListRecommendationsResponse(product_ids=selected)
