import grpc
from google.protobuf import empty_pb2

from server import product_reviews_pb2 as pb
from server import product_reviews_pb2_grpc as grpc_svc
from server import db


class ProductReviewsService(grpc_svc.ProductReviewsServicer):

    async def CreateReview(self, request, context):
        row = await db.fetchrow(
            """INSERT INTO reviews.productreviews
               (product_id, username, description, score)
               VALUES ($1, $2, $3, $4)
               RETURNING id, product_id, username, description, score""",
            request.product_id, request.username, request.description, request.score,
        )
        return self._row_to_proto(row)

    async def GetReview(self, request, context):
        row = await db.fetchrow(
            "SELECT id, product_id, username, description, score FROM reviews.productreviews WHERE id = $1",
            request.id,
        )
        if row is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("review not found")
            return pb.Review()
        return self._row_to_proto(row)

    async def ListReviewsByProduct(self, request, context):
        rows = await db.fetch(
            "SELECT id, product_id, username, description, score FROM reviews.productreviews WHERE product_id = $1",
            request.product_id,
        )
        return pb.ListReviewsResponse(
            reviews=[self._row_to_proto(r) for r in rows],
        )

    async def UpdateReview(self, request, context):
        row = await db.fetchrow(
            "SELECT id, product_id, username, description, score FROM reviews.productreviews WHERE id = $1",
            request.id,
        )
        if row is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("review not found")
            return pb.Review()

        desc = request.description if request.HasField("description") else row["description"]
        score = request.score if request.HasField("score") else row["score"]

        updated = await db.fetchrow(
            """UPDATE reviews.productreviews
               SET description = $1, score = $2
               WHERE id = $3
               RETURNING id, product_id, username, description, score""",
            desc, score, request.id,
        )
        return self._row_to_proto(updated)

    async def DeleteReview(self, request, context):
        await db.execute(
            "DELETE FROM reviews.productreviews WHERE id = $1",
            request.id,
        )
        return empty_pb2.Empty()

    @staticmethod
    def _row_to_proto(row):
        return pb.Review(
            id=row["id"],
            product_id=row["product_id"],
            username=row["username"],
            description=row["description"],
            score=float(row["score"]),
        )
