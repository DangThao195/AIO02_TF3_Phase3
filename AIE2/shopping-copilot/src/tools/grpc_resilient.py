import functools
import logging
import time

import grpc

logger = logging.getLogger("tools.grpc_resilient")


def grpc_resilient(max_retries=3, backoff=2.0):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except grpc.RpcError as e:
                    last_err = e
                    if e.code() == grpc.StatusCode.UNAVAILABLE:
                        sleep_time = backoff * (attempt + 1)
                        logger.warning(
                            f"gRPC UNAVAILABLE (attempt {attempt + 1}/{max_retries}): "
                            f"{func.__name__} retrying in {sleep_time}s | {e}"
                        )
                        time.sleep(sleep_time)
                    else:
                        break
                except Exception as e:
                    last_err = e
                    break
            logger.error(
                f"gRPC call failed after {max_retries} retries: {func.__name__} | {last_err}"
            )
            return None

        return wrapper

    return decorator
