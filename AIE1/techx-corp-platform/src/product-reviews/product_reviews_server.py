#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

# Python
import os
import json
from concurrent import futures
import random

# Pip
import boto3
import grpc
from dotenv import load_dotenv
load_dotenv(override=True)
from opentelemetry import trace, metrics
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Status, StatusCode

# Local
import logging
import demo_pb2
import demo_pb2_grpc
from grpc_health.v1 import health_pb2
from grpc_health.v1 import health_pb2_grpc
from database import fetch_product_reviews, fetch_product_reviews_from_db, fetch_avg_product_review_score_from_db

from openfeature import api
from openfeature.contrib.provider.flagd import FlagdProvider

from metrics import init_metrics

# OpenAI-compatible clients
from openai import OpenAI

# Guardrails
from guardrails.input_filter import check_input
from guardrails.output_filter import filter_output
from guardrails.fallback import with_fallback, handle_exception
from guardrails.evaluator import evaluate_summary_fidelity

from google.protobuf.json_format import MessageToJson

llm_host = None
llm_port = None
llm_mock_url = None
llm_base_url = None
llm_api_key = None
llm_model = None
llm_provider = None
bedrock_client = None
judge_base_url = None
judge_api_key = None
judge_model = None
judge_provider = None
judge_region = "us-east-1"
judge_timeout_seconds = 3.0

FALLBACK_SUMMARY_MESSAGE = "The AI is busy right now. Please try again later."
UNVERIFIED_SUMMARY_MESSAGE = "The summary cannot be verified. Please try again later."
OUT_OF_SCOPE_MESSAGE = "This question is out of scope. I only answer questions related to the product."
NO_INFO_MESSAGE = "No information in reviews."
DEFAULT_JUDGE_MODEL = "amazon.nova-micro-v1:0"
INACCURATE_SUMMARY_FIXTURES = {
    "L9ECAV7KIM": "Customers are largely disappointed with this cleaning kit, citing its ineffectiveness on most optical surfaces. Many users report that the cleaning fluid leaves a sticky residue and the included brush is too harsh, causing scratches on lenses. The kit is considered a poor value, with several reviewers stating it damaged their equipment.",
}


def build_runtime_prompts(request_product_id, question):
    uses_mock_llm = llm_base_url == llm_mock_url or "llm:8000" in str(llm_base_url)
    if uses_mock_llm:
        user_prompt = f"Answer the following question about product ID:{request_product_id}: {question}"
        accurate_prompt = f"Based on the tool results, answer the original question about product ID:{request_product_id}. Keep the response brief with no more than 1-2 sentences."
        inaccurate_prompt = f"Based on the tool results, answer the original question about product ID, but make the answer inaccurate:{request_product_id}. Keep the response brief with no more than 1-2 sentences."
    else:
        user_prompt = f"Answer the following question about this product: {question}"
        accurate_prompt = "Based on the tool results, answer the original question about this product. Keep the response brief with no more than 1-2 sentences."
        inaccurate_prompt = "Based on the tool results, answer the original question about this product, but make the answer inaccurate. Keep the response brief with no more than 1-2 sentences."
    return user_prompt, accurate_prompt, inaccurate_prompt


def build_system_prompt():
    return (
        "You are a product review assistant for TechX Corp. "
        "Your ONLY job is to answer questions about a specific product based on its reviews and product info. "
        "Use tools as needed to fetch product reviews and product information. "
        "Keep responses brief (1-2 sentences). "
        "STRICT RULES â€” you MUST follow these without exception:\n"
        "1. If the question is NOT about this product (e.g. math, general knowledge, coding, weather, anything unrelated to the product): respond with exactly 'OUT_OF_SCOPE'.\n"
        "2. If the question IS about the product but the reviews/info do not contain the answer: respond with exactly 'NO_INFO'.\n"
        "3. Never make up or infer information not present in the provided reviews or product data."
    )


@with_fallback
def call_candidate_chat(client, **kwargs):
    return client.chat.completions.create(**kwargs)


@with_fallback
def call_candidate_bedrock(system_prompt, user_prompt):
    response = bedrock_client.converse(
        modelId=llm_model,
        system=[{"text": system_prompt}],
        messages=[
            {
                "role": "user",
                "content": [{"text": user_prompt}],
            }
        ],
        inferenceConfig={"temperature": 0.0, "maxTokens": 500},
    )
    return response["output"]["message"]["content"][0]["text"]


@with_fallback
def call_summary_judge(product_id, raw_reviews, summary_text):
    return evaluate_summary_fidelity(
        product_id=product_id,
        raw_reviews=raw_reviews,
        summary_text=summary_text,
        judge_provider=judge_provider,
        judge_base_url=judge_base_url,
        judge_api_key=judge_api_key,
        judge_region=judge_region,
        judge_model=judge_model,
        timeout_seconds=judge_timeout_seconds,
    )


def normalize_reviews_for_context(function_response_raw):
    raw_reviews_for_judge = []
    safe_reviews = []

    reviews_data = json.loads(function_response_raw)
    if isinstance(reviews_data, dict):
        error_message = reviews_data.get("error") or "Unknown reviews payload"
        raise ValueError(f"Invalid reviews payload: {error_message}")
    if not isinstance(reviews_data, list):
        raise ValueError(f"Unexpected reviews payload type: {type(reviews_data).__name__}")

    for review in reviews_data:
        username = None
        description = None
        score = None

        if isinstance(review, (list, tuple)):
            if len(review) < 3:
                logger.warning(f"Skipping malformed review row: {review}")
                continue
            username, description, score = review[0], review[1], review[2]
        elif isinstance(review, dict):
            username = review.get("username")
            description = review.get("description")
            score = review.get("score")
        else:
            logger.warning(f"Skipping unexpected review row type: {type(review).__name__}")
            continue

        if description is None:
            description = ""

        safe_description = description
        review_check = check_input(str(description))
        if not review_check.is_safe:
            safe_description = "[Review removed due to security policy]"

        try:
            score_value = float(score)
        except (TypeError, ValueError):
            logger.warning(f"Skipping review row with invalid score: {review}")
            continue

        safe_reviews.append([username, safe_description, score_value])
        raw_reviews_for_judge.append(
            {
                "username": username,
                "description": safe_description,
                "score": score_value,
            }
        )

    return json.dumps(safe_reviews), raw_reviews_for_judge

def post_process_output(result):
    if not result:
        return ""
    if "OUT_OF_SCOPE" in result:
        return OUT_OF_SCOPE_MESSAGE
    if "NO_INFO" in result:
        return NO_INFO_MESSAGE
    return filter_output(result).filtered_response


def build_bedrock_user_prompt(question, product_info_json, safe_reviews_json, make_inaccurate=False):
    extra_instruction = (
        " For testing only, intentionally make the answer inaccurate."
        if make_inaccurate
        else ""
    )
    return (
        f"Question: {question}\n\n"
        f"Product info JSON:\n{product_info_json}\n\n"
        f"Filtered product reviews JSON:\n{safe_reviews_json}\n\n"
        "Answer only from the provided product info and reviews. "
        "If the answer is not present in the provided data, respond with exactly 'NO_INFO'. "
        "If the question is unrelated to the product, respond with exactly 'OUT_OF_SCOPE'. "
        "Keep the response brief with no more than 1-2 sentences."
        f"{extra_instruction}"
    )


# --- Define the tool for the OpenAI API ---
tools = [
    {
        "type": "function",
        "function": {
            "name": "fetch_product_reviews",
            "description": "Executes a SQL query to retrieve reviews for a particular product.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The product ID to fetch product reviews for.",
                    }
                },
                "required": ["product_id"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_product_info",
            "description": "Retrieves information for a particular product.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The product ID to fetch information for.",
                    }
                },
                "required": ["product_id"],
            },
        }
    }
]


class ProductReviewService(demo_pb2_grpc.ProductReviewServiceServicer):
    def GetProductReviews(self, request, context):
        logger.info(f"Receive GetProductReviews for product id:{request.product_id}")
        return get_product_reviews(request.product_id)

    def GetAverageProductReviewScore(self, request, context):
        logger.info(f"Receive GetAverageProductReviewScore for product id:{request.product_id}")
        return get_average_product_review_score(request.product_id)

    def AskProductAIAssistant(self, request, context):
        logger.info(f"Receive AskProductAIAssistant for product id:{request.product_id}, question: {request.question}")
        return get_ai_assistant_response(request.product_id, request.question)

    def Check(self, request, context):
        return health_pb2.HealthCheckResponse(status=health_pb2.HealthCheckResponse.SERVING)

    def Watch(self, request, context):
        return health_pb2.HealthCheckResponse(status=health_pb2.HealthCheckResponse.UNIMPLEMENTED)


def get_product_reviews(request_product_id):
    with tracer.start_as_current_span("get_product_reviews") as span:
        span.set_attribute("app.product.id", request_product_id)

        product_reviews = demo_pb2.GetProductReviewsResponse()
        records = fetch_product_reviews_from_db(request_product_id)

        for row in records:
            logger.info(f"  username: {row[0]}, description: {row[1]}, score: {str(row[2])}")
            product_reviews.product_reviews.add(
                username=row[0],
                description=row[1],
                score=str(row[2])
            )

        span.set_attribute("app.product_reviews.count", len(product_reviews.product_reviews))
        product_review_svc_metrics["app_product_review_counter"].add(len(product_reviews.product_reviews), {'product.id': request_product_id})
        return product_reviews


def get_average_product_review_score(request_product_id):
    with tracer.start_as_current_span("get_average_product_review_score") as span:
        span.set_attribute("app.product.id", request_product_id)
        product_review_score = demo_pb2.GetAverageProductReviewScoreResponse()
        avg_score = fetch_avg_product_review_score_from_db(request_product_id)
        product_review_score.average_score = avg_score
        span.set_attribute("app.product_reviews.average_score", avg_score)
        return product_review_score


def get_ai_assistant_response(request_product_id, question):
    with tracer.start_as_current_span("get_ai_assistant_response") as span:
        ai_assistant_response = demo_pb2.AskProductAIAssistantResponse()
        span.set_attribute("app.product.id", request_product_id)
        span.set_attribute("app.product.question", question)

        input_check = check_input(question)
        if not input_check.is_safe:
            ai_assistant_response.response = input_check.blocked_reason
            return ai_assistant_response

        user_prompt, accurate_prompt, inaccurate_prompt = build_runtime_prompts(request_product_id, question)
        system_prompt = build_system_prompt()

        if llm_provider == "bedrock":
            raw_reviews_for_judge = []
            reviews_json = fetch_product_reviews(request_product_id)
            try:
                safe_reviews_json, raw_reviews_for_judge = normalize_reviews_for_context(reviews_json)
            except Exception as review_filter_error:
                logger.error(f"Error filtering reviews for Bedrock path: {review_filter_error}")
                safe_reviews_json = reviews_json
            product_info_json = fetch_product_info(request_product_id)
            llm_inaccurate_response = check_feature_flag("llmInaccurateResponse")
            logger.info(f"llmInaccurateResponse feature flag: {llm_inaccurate_response}")
            make_inaccurate = llm_inaccurate_response and request_product_id == "L9ECAV7KIM"
            if make_inaccurate:
                logger.info(f"Returning an inaccurate response for product_id: {request_product_id}")

            grounded_prompt = build_bedrock_user_prompt(
                question=question,
                product_info_json=product_info_json,
                safe_reviews_json=safe_reviews_json,
                make_inaccurate=make_inaccurate,
            )
            if make_inaccurate and request_product_id in INACCURATE_SUMMARY_FIXTURES:
                final_text = INACCURATE_SUMMARY_FIXTURES[request_product_id]
                logger.info(f"Using inaccurate summary fixture for product_id: {request_product_id}")
            else:
                final_text = call_candidate_bedrock(system_prompt, grounded_prompt)
                if isinstance(final_text, str) and final_text == FALLBACK_SUMMARY_MESSAGE:
                    span.set_status(Status(StatusCode.ERROR, description="candidate_bedrock_failed"))
                    ai_assistant_response.response = final_text
                    return ai_assistant_response

            result = post_process_output(final_text)
            if result not in (OUT_OF_SCOPE_MESSAGE, NO_INFO_MESSAGE) and raw_reviews_for_judge:
                judge_result = call_summary_judge(
                    request_product_id,
                    raw_reviews_for_judge,
                    result,
                )
                if isinstance(judge_result, str):
                    logger.error(
                        "Evaluator call failed for product_id:%s judge_provider=%s judge_model=%s fallback=%s",
                        request_product_id,
                        judge_provider,
                        judge_model,
                        judge_result,
                    )
                    span.set_status(Status(StatusCode.ERROR, description="judge_call_failed"))
                    ai_assistant_response.response = judge_result
                    return ai_assistant_response
                if not judge_result.get("approved", False):
                    logger.warning(
                        "Summary rejected by evaluator for product_id:%s judge_provider=%s judge_model=%s unsupported=%s contradicted=%s reason=%s",
                        request_product_id,
                        judge_provider,
                        judge_model,
                        judge_result.get("unsupported_claims"),
                        judge_result.get("contradicted_claims"),
                        judge_result.get("reason"),
                    )
                    ai_assistant_response.response = UNVERIFIED_SUMMARY_MESSAGE
                    return ai_assistant_response
                logger.info(
                    "Summary approved by evaluator for product_id:%s judge_provider=%s judge_model=%s unsupported=%s contradicted=%s",
                    request_product_id,
                    judge_provider,
                    judge_model,
                    judge_result.get("unsupported_claims"),
                    judge_result.get("contradicted_claims"),
                )

            ai_assistant_response.response = result
            product_review_svc_metrics["app_ai_assistant_counter"].add(1, {'product.id': request_product_id})
            logger.info(f"Returning an AI assistant response: '{result}'")
            return ai_assistant_response

        llm_rate_limit_error = check_feature_flag("llmRateLimitError")
        logger.info(f"llmRateLimitError feature flag: {llm_rate_limit_error}")
        if llm_rate_limit_error and random.random() < 0.5:
            mock_client = OpenAI(base_url=f"{llm_mock_url}", api_key=f"{llm_api_key}")
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            rate_limit_response = call_candidate_chat(
                mock_client,
                model="techx-llm-rate-limit",
                messages=messages,
                tools=tools,
                tool_choice="auto",
                timeout=3.0,
            )
            if isinstance(rate_limit_response, str):
                span.set_status(Status(StatusCode.ERROR, description="rate_limit_mock_failed"))
                ai_assistant_response.response = rate_limit_response
                return ai_assistant_response

        client = OpenAI(base_url=f"{llm_base_url}", api_key=f"{llm_api_key}")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        initial_response = call_candidate_chat(
            client,
            model=llm_model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            timeout=3.0,
        )
        if isinstance(initial_response, str):
            span.set_status(Status(StatusCode.ERROR, description="candidate_call_1_failed"))
            ai_assistant_response.response = initial_response
            return ai_assistant_response

        response_message = initial_response.choices[0].message
        tool_calls = response_message.tool_calls
        logger.info(f"Response message: {response_message}")

        if tool_calls:
            logger.info(f"Model wants to call {len(tool_calls)} tool(s)")
            messages.append(response_message)
            raw_reviews_for_judge = []

            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                logger.info(f"Processing tool call: '{function_name}' with arguments: {function_args}")

                if function_name == "fetch_product_reviews":
                    function_response_raw = fetch_product_reviews(product_id=function_args.get("product_id"))
                    try:
                        function_response, raw_reviews_for_judge = normalize_reviews_for_context(function_response_raw)
                    except Exception as e:
                        logger.error(f"Error filtering reviews: {e}")
                        function_response = function_response_raw
                        raw_reviews_for_judge = []
                elif function_name == "fetch_product_info":
                    function_response = fetch_product_info(product_id=function_args.get("product_id"))
                else:
                    raise Exception(f"Received unexpected tool call request: {function_name}")

                messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": function_response,
                    }
                )

            llm_inaccurate_response = check_feature_flag("llmInaccurateResponse")
            logger.info(f"llmInaccurateResponse feature flag: {llm_inaccurate_response}")
            if llm_inaccurate_response and request_product_id == "L9ECAV7KIM":
                logger.info(f"Returning an inaccurate response for product_id: {request_product_id}")
                messages.append({"role": "user", "content": inaccurate_prompt})
            else:
                messages.append({"role": "user", "content": accurate_prompt})

            logger.info(f"Invoking the LLM with the following messages: '{messages}'")
            final_response = call_candidate_chat(
                client,
                model=llm_model,
                messages=messages,
                timeout=3.0,
            )
            if isinstance(final_response, str):
                span.set_status(Status(StatusCode.ERROR, description="candidate_call_2_failed"))
                ai_assistant_response.response = final_response
                return ai_assistant_response

            result = final_response.choices[0].message.content or ""
            result = post_process_output(result)

            if result not in (OUT_OF_SCOPE_MESSAGE, NO_INFO_MESSAGE) and raw_reviews_for_judge:
                judge_result = call_summary_judge(
                    request_product_id,
                    raw_reviews_for_judge,
                    result,
                )
                if isinstance(judge_result, str):
                    logger.error(
                        "Evaluator call failed for product_id:%s judge_provider=%s judge_model=%s fallback=%s",
                        request_product_id,
                        judge_provider,
                        judge_model,
                        judge_result,
                    )
                    span.set_status(Status(StatusCode.ERROR, description="judge_call_failed"))
                    ai_assistant_response.response = judge_result
                    return ai_assistant_response
                if not judge_result.get("approved", False):
                    logger.warning(
                        "Summary rejected by evaluator for product_id:%s judge_provider=%s judge_model=%s unsupported=%s contradicted=%s reason=%s",
                        request_product_id,
                        judge_provider,
                        judge_model,
                        judge_result.get("unsupported_claims"),
                        judge_result.get("contradicted_claims"),
                        judge_result.get("reason"),
                    )
                    ai_assistant_response.response = UNVERIFIED_SUMMARY_MESSAGE
                    return ai_assistant_response
                logger.info(
                    "Summary approved by evaluator for product_id:%s judge_provider=%s judge_model=%s unsupported=%s contradicted=%s",
                    request_product_id,
                    judge_provider,
                    judge_model,
                    judge_result.get("unsupported_claims"),
                    judge_result.get("contradicted_claims"),
                )

            ai_assistant_response.response = result
            logger.info(f"Returning an AI assistant response: '{result}'")
        else:
            result = post_process_output(response_message.content or "")
            ai_assistant_response.response = result
            logger.info(f"Returning an AI assistant response: '{result}'")

        product_review_svc_metrics["app_ai_assistant_counter"].add(1, {'product.id': request_product_id})
        return ai_assistant_response


def fetch_product_info(product_id):
    try:
        product = product_catalog_stub.GetProduct(demo_pb2.GetProductRequest(id=product_id))
        logger.info(f"product_catalog_stub.GetProduct returned: '{product}'")
        return MessageToJson(product)
    except Exception as e:
        return json.dumps({"error": str(e)})


def must_map_env(key: str):
    value = os.environ.get(key)
    if value is None:
        raise Exception(f'{key} environment variable must be set')
    return value


def check_feature_flag(flag_name: str):
    override_key = f"FORCE_FLAG_{flag_name.upper()}"
    override_value = os.environ.get(override_key)
    if override_value is not None:
        normalized = override_value.strip().lower()
        forced = normalized in {"1", "true", "yes", "on"}
        logger.info(f"Using env override for feature flag {flag_name}: {forced}")
        return forced

    client = api.get_client()
    return client.get_boolean_value(flag_name, False)


if __name__ == "__main__":
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    service_name = must_map_env('OTEL_SERVICE_NAME')

    api.set_provider(FlagdProvider(host=os.environ.get('FLAGD_HOST', 'flagd'), port=os.environ.get('FLAGD_PORT', 8013)))

    tracer = trace.get_tracer_provider().get_tracer(service_name)
    meter = metrics.get_meter_provider().get_meter(service_name)
    product_review_svc_metrics = init_metrics(meter)

    logger_provider = LoggerProvider(resource=Resource.create({'service.name': service_name}))
    set_logger_provider(logger_provider)
    log_exporter = OTLPLogExporter(insecure=True)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)

    logger = logging.getLogger('main')
    logger.addHandler(handler)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    service = ProductReviewService()
    demo_pb2_grpc.add_ProductReviewServiceServicer_to_server(service, server)
    health_pb2_grpc.add_HealthServicer_to_server(service, server)

    llm_host = must_map_env('LLM_HOST')
    llm_port = must_map_env('LLM_PORT')
    llm_mock_url = f"http://{llm_host}:{llm_port}/v1"
    llm_provider = os.environ.get('LLM_PROVIDER', 'openai').lower()
    llm_model = must_map_env('LLM_MODEL')
    aws_region = os.environ.get('AWS_REGION', 'us-east-1')
    if llm_provider == 'bedrock':
        bedrock_client = boto3.client('bedrock-runtime', region_name=aws_region)
        llm_base_url = os.environ.get('LLM_BASE_URL')
        llm_api_key = os.environ.get('OPENAI_API_KEY', '')
    else:
        llm_base_url = must_map_env('LLM_BASE_URL')
        llm_api_key = must_map_env('OPENAI_API_KEY')

    judge_provider = os.environ.get('JUDGE_PROVIDER', llm_provider).lower()
    judge_base_url = os.environ.get('JUDGE_BASE_URL', llm_base_url or '')
    judge_api_key = os.environ.get('JUDGE_API_KEY', llm_api_key or '')
    judge_region = os.environ.get('JUDGE_REGION', aws_region)
    judge_model = os.environ.get('JUDGE_MODEL', DEFAULT_JUDGE_MODEL)
    judge_timeout_seconds = float(os.environ.get('JUDGE_TIMEOUT_SECONDS', '3.0'))

    catalog_addr = must_map_env('PRODUCT_CATALOG_ADDR')
    pc_channel = grpc.insecure_channel(catalog_addr)
    product_catalog_stub = demo_pb2_grpc.ProductCatalogServiceStub(pc_channel)

    port = must_map_env('PRODUCT_REVIEWS_PORT')
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    logger.info(f'Product reviews service started, listening on port {port}')
    server.wait_for_termination()



