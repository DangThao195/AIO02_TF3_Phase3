import grpc
from google.protobuf import empty_pb2

from server import accounting_pb2 as pb
from server import accounting_pb2_grpc as grpc_svc
from server import db


class AccountingService(grpc_svc.AccountingServicer):

    async def CreateOrder(self, request, context):
        await db.execute(
            "INSERT INTO accounting.\"order\" (order_id) VALUES ($1) ON CONFLICT DO NOTHING",
            request.order_id,
        )
        row = await db.fetchrow(
            "SELECT order_id FROM accounting.\"order\" WHERE order_id = $1",
            request.order_id,
        )
        if row is None:
            context.set_code(grpc.StatusCode.ALREADY_EXISTS)
            context.set_details("order already exists")
            return pb.Order()
        return pb.Order(order_id=row["order_id"])

    async def GetOrder(self, request, context):
        order_row = await db.fetchrow(
            "SELECT order_id FROM accounting.\"order\" WHERE order_id = $1",
            request.order_id,
        )
        if order_row is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("order not found")
            return pb.Order()

        item_rows = await db.fetch(
            """SELECT product_id, quantity, item_cost_currency_code, item_cost_units, item_cost_nanos
               FROM accounting.orderitem WHERE order_id = $1""",
            request.order_id,
        )
        shipping_row = await db.fetchrow(
            """SELECT shipping_tracking_id, shipping_cost_currency_code, shipping_cost_units,
                      shipping_cost_nanos, street_address, city, state, country, zip_code, order_id
               FROM accounting.shipping WHERE order_id = $1""",
            request.order_id,
        )

        items = [
            pb.OrderItem(
                product_id=r["product_id"],
                quantity=r["quantity"],
                cost_currency_code=r["item_cost_currency_code"],
                cost_units=r["item_cost_units"],
                cost_nanos=r["item_cost_nanos"],
            )
            for r in item_rows
        ]

        shipping = None
        if shipping_row:
            shipping = pb.Shipping(
                shipping_tracking_id=shipping_row["shipping_tracking_id"],
                shipping_cost_currency_code=shipping_row["shipping_cost_currency_code"],
                shipping_cost_units=shipping_row["shipping_cost_units"],
                shipping_cost_nanos=shipping_row["shipping_cost_nanos"],
                street_address=shipping_row["street_address"],
                city=shipping_row["city"],
                state=shipping_row["state"],
                country=shipping_row["country"],
                zip_code=shipping_row["zip_code"],
                order_id=shipping_row["order_id"],
            )

        return pb.Order(order_id=order_row["order_id"], items=items, shipping=shipping)

    async def AddOrderItem(self, request, context):
        exists = await db.fetchrow(
            "SELECT 1 FROM accounting.\"order\" WHERE order_id = $1",
            request.order_id,
        )
        if exists is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("order not found")
            return pb.OrderItem()

        await db.execute(
            """INSERT INTO accounting.orderitem
               (order_id, product_id, quantity, item_cost_currency_code, item_cost_units, item_cost_nanos)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (order_id, product_id) DO UPDATE SET
               quantity = excluded.quantity,
               item_cost_currency_code = excluded.item_cost_currency_code,
               item_cost_units = excluded.item_cost_units,
               item_cost_nanos = excluded.item_cost_nanos""",
            request.order_id,
            request.product_id,
            request.quantity,
            request.cost_currency_code,
            request.cost_units,
            request.cost_nanos,
        )
        return pb.OrderItem(
            product_id=request.product_id,
            quantity=request.quantity,
            cost_currency_code=request.cost_currency_code,
            cost_units=request.cost_units,
            cost_nanos=request.cost_nanos,
        )

    async def SetShipping(self, request, context):
        exists = await db.fetchrow(
            "SELECT 1 FROM accounting.\"order\" WHERE order_id = $1",
            request.order_id,
        )
        if exists is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("order not found")
            return pb.Shipping()

        await db.execute(
            """INSERT INTO accounting.shipping
               (shipping_tracking_id, shipping_cost_currency_code, shipping_cost_units,
                shipping_cost_nanos, street_address, city, state, country, zip_code, order_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
               ON CONFLICT (shipping_tracking_id) DO UPDATE SET
               shipping_cost_currency_code = excluded.shipping_cost_currency_code,
               shipping_cost_units = excluded.shipping_cost_units,
               shipping_cost_nanos = excluded.shipping_cost_nanos,
               street_address = excluded.street_address,
               city = excluded.city,
               state = excluded.state,
               country = excluded.country,
               zip_code = excluded.zip_code""",
            request.shipping_tracking_id,
            request.shipping_cost_currency_code,
            request.shipping_cost_units,
            request.shipping_cost_nanos,
            request.street_address,
            request.city,
            request.state,
            request.country,
            request.zip_code,
            request.order_id,
        )
        return pb.Shipping(
            shipping_tracking_id=request.shipping_tracking_id,
            shipping_cost_currency_code=request.shipping_cost_currency_code,
            shipping_cost_units=request.shipping_cost_units,
            shipping_cost_nanos=request.shipping_cost_nanos,
            street_address=request.street_address,
            city=request.city,
            state=request.state,
            country=request.country,
            zip_code=request.zip_code,
            order_id=request.order_id,
        )

    async def GetShipping(self, request, context):
        row = await db.fetchrow(
            """SELECT shipping_tracking_id, shipping_cost_currency_code, shipping_cost_units,
                      shipping_cost_nanos, street_address, city, state, country, zip_code, order_id
               FROM accounting.shipping WHERE shipping_tracking_id = $1""",
            request.shipping_tracking_id,
        )
        if row is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("shipping not found")
            return pb.Shipping()
        return pb.Shipping(
            shipping_tracking_id=row["shipping_tracking_id"],
            shipping_cost_currency_code=row["shipping_cost_currency_code"],
            shipping_cost_units=row["shipping_cost_units"],
            shipping_cost_nanos=row["shipping_cost_nanos"],
            street_address=row["street_address"],
            city=row["city"],
            state=row["state"],
            country=row["country"],
            zip_code=row["zip_code"],
            order_id=row["order_id"],
        )

    async def DeleteOrder(self, request, context):
        await db.execute(
            "DELETE FROM accounting.\"order\" WHERE order_id = $1",
            request.order_id,
        )
        return empty_pb2.Empty()
