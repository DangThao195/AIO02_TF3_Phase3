import asyncio
import logging

import grpc.aio
from aiohttp import web

from server.config import GRPC_PORT
from server.db import init_db, close_db

from server.handlers.product_reviews_service import ProductReviewsService
from server.handlers.products_service import ProductsService
from server.handlers.accounting_service import AccountingService

from server.handlers.demo_catalog_service import DemoCatalogService
from server.handlers.demo_cart_service import DemoCartService
from server.handlers.demo_review_service import DemoReviewService
from server.handlers.demo_recommendation_service import DemoRecommendationService
from server.handlers.demo_currency_service import DemoCurrencyService

from server import product_reviews_pb2_grpc
from server import products_pb2_grpc
from server import accounting_pb2_grpc
from server import demo_pb2_grpc

_HTTP_PORT = 50052

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def shipping_quote(request):
    return web.json_response({
        "cost_usd": {
            "currency_code": "USD",
            "units": 5,
            "nanos": 0,
        }
    })


def _shipping_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/v1/shipping/quote", shipping_quote)
    return app


_DEMO_SERVICES: dict[int, tuple] = {
    3550: (demo_pb2_grpc.add_ProductCatalogServiceServicer_to_server, DemoCatalogService),
    7070: (demo_pb2_grpc.add_CartServiceServicer_to_server, DemoCartService),
    8081: (demo_pb2_grpc.add_RecommendationServiceServicer_to_server, DemoRecommendationService),
    9090: (demo_pb2_grpc.add_ProductReviewServiceServicer_to_server, DemoReviewService),
    7001: (demo_pb2_grpc.add_CurrencyServiceServicer_to_server, DemoCurrencyService),
}


async def serve() -> None:
    await init_db()
    logger.info("database ready")

    servers: list[grpc.aio.Server] = []

    # ── Legacy gRPC server (port 50051) ──
    server_legacy = grpc.aio.server()
    server_legacy.add_insecure_port(f"0.0.0.0:{GRPC_PORT}")

    product_reviews_pb2_grpc.add_ProductReviewsServicer_to_server(
        ProductReviewsService(), server_legacy,
    )
    products_pb2_grpc.add_ProductsServicer_to_server(
        ProductsService(), server_legacy,
    )
    accounting_pb2_grpc.add_AccountingServicer_to_server(
        AccountingService(), server_legacy,
    )

    await server_legacy.start()
    servers.append(server_legacy)
    logger.info("legacy gRPC server listening on 0.0.0.0:%d", GRPC_PORT)

    # ── Demo gRPC servers ──
    for port, (registrator, servicer_cls) in _DEMO_SERVICES.items():
        s = grpc.aio.server()
        s.add_insecure_port(f"0.0.0.0:{port}")
        registrator(servicer_cls(), s)
        await s.start()
        servers.append(s)
        logger.info("demo gRPC service ready on 0.0.0.0:%d", port)

    # ── HTTP shipping server ──
    runner = web.AppRunner(_shipping_app())
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", _HTTP_PORT)
    await site.start()
    logger.info("HTTP shipping ready on 0.0.0.0:%d", _HTTP_PORT)

    logger.info("all servers ready")

    try:
        await asyncio.Event().wait()
    finally:
        for s in servers:
            await s.stop(5)
        await runner.cleanup()
        await close_db()


if __name__ == "__main__":
    asyncio.run(serve())
