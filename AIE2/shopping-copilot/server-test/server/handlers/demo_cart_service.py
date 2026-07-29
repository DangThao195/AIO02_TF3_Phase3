import grpc

from server import demo_pb2 as pb
from server import demo_pb2_grpc as grpc_svc
from server import db


class DemoCartService(grpc_svc.CartServiceServicer):

    async def AddItem(self, request, context):
        user_id = request.user_id
        product_id = request.item.product_id
        quantity = request.item.quantity

        existing = await db.fetchrow(
            "SELECT quantity FROM cart WHERE user_id = ? AND product_id = ?",
            user_id, product_id,
        )
        if existing:
            new_qty = existing["quantity"] + quantity
            await db.execute(
                "UPDATE cart SET quantity = ? WHERE user_id = ? AND product_id = ?",
                new_qty, user_id, product_id,
            )
        else:
            await db.execute(
                "INSERT INTO cart (user_id, product_id, quantity) VALUES (?, ?, ?)",
                user_id, product_id, quantity,
            )
        return pb.Empty()

    async def GetCart(self, request, context):
        user_id = request.user_id
        rows = await db.fetch(
            "SELECT product_id, quantity FROM cart WHERE user_id = ? ORDER BY product_id",
            user_id,
        )
        items = [pb.CartItem(product_id=r["product_id"], quantity=r["quantity"]) for r in rows]
        return pb.Cart(user_id=user_id, items=items)

    async def EmptyCart(self, request, context):
        await db.execute("DELETE FROM cart WHERE user_id = ?", request.user_id)
        return pb.Empty()
