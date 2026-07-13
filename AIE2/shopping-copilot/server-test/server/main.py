import asyncio
import logging

import grpc.aio

from server.config import GRPC_PORT
from server.db import init_pool, close_pool

from server.handlers.product_reviews_service import ProductReviewsService
from server.handlers.products_service import ProductsService
from server.handlers.accounting_service import AccountingService

from server import product_reviews_pb2_grpc
from server import products_pb2_grpc
from server import accounting_pb2_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def serve() -> None:
    await init_pool()
    logger.info("database pool ready")

    server = grpc.aio.server()
    server.add_insecure_port(f"0.0.0.0:{GRPC_PORT}")

    product_reviews_pb2_grpc.add_ProductReviewsServicer_to_server(
        ProductReviewsService(), server,
    )
    products_pb2_grpc.add_ProductsServicer_to_server(
        ProductsService(), server,
    )
    accounting_pb2_grpc.add_AccountingServicer_to_server(
        AccountingService(), server,
    )

    await server.start()
    logger.info("gRPC server listening on 0.0.0.0:%d", GRPC_PORT)

    try:
        await server.wait_for_termination()
    finally:
        await server.stop(0)
        await close_pool()


if __name__ == "__main__":
    asyncio.run(serve())
