import grpc
from google.protobuf import empty_pb2

from server import product_reviews_pb2 as pb
from server import product_reviews_pb2_grpc as grpc_svc
from server import db


class ProductReviewsService(grpc_svc.ProductReviewsServicer):

    async def CreateReview(self, request, context):
        await db.execute(
            """INSERT INTO productreviews
               (product_id, username, description, score)
               VALUES (?, ?, ?, ?)""",
            request.product_id, request.username, request.description, request.score,
        )
        row = await db.fetchrow(
            "SELECT id, product_id, username, description, score FROM productreviews WHERE id = last_insert_rowid()",
        )
        return self._row_to_proto(row)

    async def GetReview(self, request, context):
        row = await db.fetchrow(
            "SELECT id, product_id, username, description, score FROM productreviews WHERE id = ?",
            request.id,
        )
        if row is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("review not found")
            return pb.Review()
        return self._row_to_proto(row)

    async def ListReviewsByProduct(self, request, context):
        rows = await db.fetch(
            "SELECT id, product_id, username, description, score FROM productreviews WHERE product_id = ?",
            request.product_id,
        )
        return pb.ListReviewsResponse(
            reviews=[self._row_to_proto(r) for r in rows],
        )

    async def UpdateReview(self, request, context):
        row = await db.fetchrow(
            "SELECT id, product_id, username, description, score FROM productreviews WHERE id = ?",
            request.id,
        )
        if row is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("review not found")
            return pb.Review()

        desc = request.description if request.HasField("description") else row["description"]
        score = request.score if request.HasField("score") else row["score"]

        await db.execute(
            "UPDATE productreviews SET description = ?, score = ? WHERE id = ?",
            desc, score, request.id,
        )
        updated = await db.fetchrow(
            "SELECT id, product_id, username, description, score FROM productreviews WHERE id = ?",
            request.id,
        )
        return self._row_to_proto(updated)

    async def DeleteReview(self, request, context):
        await db.execute(
            "DELETE FROM productreviews WHERE id = ?",
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
