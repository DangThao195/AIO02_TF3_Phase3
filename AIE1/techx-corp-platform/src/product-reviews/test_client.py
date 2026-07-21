import grpc
import demo_pb2
import demo_pb2_grpc
import sys

def run(port="3551", product_id="L9ECAV7KIM", question="Can you summarize the product reviews?"):
    channel = grpc.insecure_channel(f"localhost:{port}")
    stub = demo_pb2_grpc.ProductReviewServiceStub(channel)
    
    print(f"Sending AskProductAIAssistant request to localhost:{port}...")
    print(f"Product ID: {product_id}")
    print(f"Question: {question}\n")
    
    try:
        response = stub.AskProductAIAssistant(
            demo_pb2.AskProductAIAssistantRequest(
                product_id=product_id,
                question=question
            )
        )
        print("=== AI Response ===")
        print(response.response)
        print("===================")
    except grpc.RpcError as e:
        print(f"gRPC Error: {e.code()} - {e.details()}")
    except Exception as e:
        print(f"Error calling gRPC: {e}")

if __name__ == "__main__":
    # Cho phép truyền tham số qua dòng lệnh: python test_client.py <port> <product_id> <question>
    target_port = sys.argv[1] if len(sys.argv) > 1 else "3551"
    target_product_id = sys.argv[2] if len(sys.argv) > 2 else "L9ECAV7KIM"
    target_question = sys.argv[3] if len(sys.argv) > 3 else "Can you summarize the product reviews?"
    run(port=target_port, product_id=target_product_id, question=target_question)
