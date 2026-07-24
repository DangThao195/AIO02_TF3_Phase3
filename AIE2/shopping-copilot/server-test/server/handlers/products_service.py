import grpc
from google.protobuf import empty_pb2

from server import products_pb2 as pb
from server import products_pb2_grpc as grpc_svc
from server import db


class ProductsService(grpc_svc.ProductsServicer):

    async def GetProduct(self, request, context):
        row = await db.fetchrow(
            "SELECT id, name, description, picture, price_currency_code, price_units, price_nanos, categories FROM products WHERE id = ?",
            request.id,
        )
        if row is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("product not found")
            return pb.Product()
        return self._row_to_proto(row)

    async def ListProducts(self, request, context):
        rows = await db.fetch(
            "SELECT id, name, description, picture, price_currency_code, price_units, price_nanos, categories FROM products ORDER BY name",
        )
        return pb.ListProductsResponse(
            products=[self._row_to_proto(r) for r in rows],
        )

    async def SearchProducts(self, request, context):
        pattern = f"%{request.query}%"
        rows = await db.fetch(
            """SELECT id, name, description, picture, price_currency_code, price_units, price_nanos, categories
               FROM products
               WHERE name LIKE ? OR description LIKE ?
               ORDER BY name""",
            pattern, pattern,
        )
        return pb.ListProductsResponse(
            products=[self._row_to_proto(r) for r in rows],
        )

    @staticmethod
    def _row_to_proto(row):
        return pb.Product(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            picture=row["picture"],
            price_currency_code=row["price_currency_code"],
            price_units=row["price_units"],
            price_nanos=row["price_nanos"],
            categories=row["categories"],
        )
