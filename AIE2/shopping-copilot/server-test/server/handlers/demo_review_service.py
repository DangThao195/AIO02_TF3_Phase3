from server import demo_pb2 as pb
from server import demo_pb2_grpc as grpc_svc
from server import db


class DemoReviewService(grpc_svc.ProductReviewServiceServicer):

    async def GetProductReviews(self, request, context):
        rows = await db.fetch(
            "SELECT username, description, score FROM productreviews WHERE product_id = ? ORDER BY id",
            request.product_id,
        )
        reviews = [
            pb.ProductReview(
                username=r["username"],
                description=r["description"],
                score=str(r["score"]),
            )
            for r in rows
        ]
        return pb.GetProductReviewsResponse(product_reviews=reviews)

    async def GetAverageProductReviewScore(self, request, context):
        row = await db.fetchrow(
            "SELECT AVG(score) as avg_score FROM productreviews WHERE product_id = ?",
            request.product_id,
        )
        avg = row["avg_score"] if row and row["avg_score"] else 0.0
        return pb.GetAverageProductReviewScoreResponse(average_score=str(round(avg, 2)))

    async def AskProductAIAssistant(self, request, context):
        return pb.AskProductAIAssistantResponse(
            response=(
                f"This product ({request.product_id}) is well-regarded by customers. "
                f"For your question '{request.question}': based on available reviews, "
                f"customers find this product to be of good quality and value. "
                f"We recommend checking the customer reviews for more specific feedback."
            )
        )
