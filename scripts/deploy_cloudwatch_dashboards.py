"""
deploy_cloudwatch_dashboards.py
-------------------------------------------------------------------------
Cập nhật 2 CloudWatch Dashboards dùng METRIC NATIVE CHÍNH THỨC CỦA AWS:
  - Namespace: 'AWS/Billing'
  - Metric Name: 'EstimatedCharges'
  - Dimensions: Currency='USD', ServiceName='...'
  - Timeframe: Từ ngày 01/07/2026 đến 31/07/2026 ('2026-07-01T00:00:00Z' đến '2026-07-31T23:59:59Z')

LƯU Ý AN TOÀN: 100% dùng API Boto3 put_dashboard (us-east-1). Không Terraform.
"""

import boto3
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

REGION = "us-east-1"
START_TIME = "2026-07-01T00:00:00Z"
END_TIME = "2026-07-31T23:59:59Z"

# Các AWS Services phổ biến có trong AWS Billing
AWS_SERVICES = [
    ("AmazonEC2", "Amazon EC2 Compute & Instances"),
    ("AmazonRDS", "Amazon RDS Relational Database"),
    ("AmazonEKS", "Amazon Elastic Kubernetes Service (EKS)"),
    ("AmazonS3", "Amazon Simple Storage Service (S3)"),
    ("AmazonCloudWatch", "Amazon CloudWatch Logs & Metrics"),
    ("AWSKMS", "AWS Key Management Service (KMS)"),
    ("AmazonMSK", "Amazon Managed Streaming for Kafka (MSK)"),
    ("AmazonOpenSearchService", "Amazon OpenSearch Service"),
    ("ec2-other", "EC2 Other / Elastic IPs / Storage")
]

def build_region_dashboard_json():
    """Tạo JSON definition cho Dashboard 1: Budget-Cost-By-Region (dùng AWS/Billing gốc)."""
    # Total Account Billing Metric
    total_metric = [["AWS/Billing", "EstimatedCharges", "Currency", "USD", {"label": "Total Account Estimated Charges ($USD)", "color": "#06b6d4", "period": 86400}]]
    
    # Regional / Service Breakdown Metrics
    service_breakdown_metrics = []
    for svc_code, svc_label in AWS_SERVICES:
        service_breakdown_metrics.append(["AWS/Billing", "EstimatedCharges", "ServiceName", svc_code, "Currency", "USD", {"label": f"{svc_label}", "period": 86400}])

    dashboard_body = {
        "start": START_TIME,
        "end": END_TIME,
        "widgets": [
            {
                "type": "text",
                "x": 0,
                "y": 0,
                "width": 24,
                "height": 2,
                "properties": {
                    "markdown": "# 🌐 Dashboard 1: AWS Total Budget & Cost Statistics (Native AWS/Billing)\n**Theo dõi tổng chi phí AWS Account từ 01/07/2026 đến 31/07/2026 (Region: us-east-1)**"
                }
            },
            {
                "type": "metric",
                "x": 0,
                "y": 2,
                "width": 12,
                "height": 9,
                "properties": {
                    "metrics": total_metric,
                    "view": "timeSeries",
                    "stacked": False,
                    "region": REGION,
                    "title": "📈 Total AWS Account Estimated Charges ($USD) - July 2026 Line Chart",
                    "period": 86400,
                    "stat": "Maximum",
                    "yAxis": {
                        "left": {
                            "label": "USD ($)",
                            "showUnits": False
                        }
                    }
                }
            },
            {
                "type": "metric",
                "x": 12,
                "y": 2,
                "width": 12,
                "height": 9,
                "properties": {
                    "metrics": service_breakdown_metrics,
                    "view": "timeSeries",
                    "stacked": True,
                    "region": REGION,
                    "title": "📊 Regional/Service Cumulative Spend Breakdown (Stacked Line Chart)",
                    "period": 86400,
                    "stat": "Maximum",
                    "yAxis": {
                        "left": {
                            "label": "USD ($)",
                            "showUnits": False
                        }
                    }
                }
            },
            {
                "type": "metric",
                "x": 0,
                "y": 11,
                "width": 24,
                "height": 7,
                "properties": {
                    "metrics": total_metric,
                    "view": "singleValue",
                    "region": REGION,
                    "title": "💰 Current Total Month Estimated Charges (Single Value Summary)",
                    "period": 86400,
                    "stat": "Maximum"
                }
            }
        ]
    }
    return json.dumps(dashboard_body)

def build_service_dashboard_json():
    """Tạo JSON definition cho Dashboard 2: Budget-Cost-By-Service (dùng AWS/Billing gốc)."""
    service_line_metrics = []
    for svc_code, svc_label in AWS_SERVICES:
        service_line_metrics.append(["AWS/Billing", "EstimatedCharges", "ServiceName", svc_code, "Currency", "USD", {"label": f"{svc_label}", "period": 86400}])

    dashboard_body = {
        "start": START_TIME,
        "end": END_TIME,
        "widgets": [
            {
                "type": "text",
                "x": 0,
                "y": 0,
                "width": 24,
                "height": 2,
                "properties": {
                    "markdown": "# 🛠️ Dashboard 2: AWS Services Cost Statistics (Native AWS/Billing)\n**Phân tích tổng chi phí theo từng dịch vụ AWS từ 01/07/2026 đến 31/07/2026**"
                }
            },
            {
                "type": "metric",
                "x": 0,
                "y": 2,
                "width": 12,
                "height": 9,
                "properties": {
                    "metrics": service_line_metrics,
                    "view": "timeSeries",
                    "stacked": False,
                    "region": REGION,
                    "title": "⚡ AWS Estimated Charges by Service ($USD) - July 2026 Line Chart",
                    "period": 86400,
                    "stat": "Maximum",
                    "yAxis": {
                        "left": {
                            "label": "USD ($)",
                            "showUnits": False
                        }
                    }
                }
            },
            {
                "type": "metric",
                "x": 12,
                "y": 2,
                "width": 12,
                "height": 9,
                "properties": {
                    "metrics": service_line_metrics,
                    "view": "timeSeries",
                    "stacked": True,
                    "region": REGION,
                    "title": "📊 Cumulative AWS Services Spend Breakdown (Stacked Line Chart)",
                    "period": 86400,
                    "stat": "Maximum",
                    "yAxis": {
                        "left": {
                            "label": "USD ($)",
                            "showUnits": False
                        }
                    }
                }
            },
            {
                "type": "metric",
                "x": 0,
                "y": 11,
                "width": 24,
                "height": 7,
                "properties": {
                    "metrics": service_line_metrics,
                    "view": "bar",
                    "region": REGION,
                    "title": "🧱 AWS Services Cost Distribution Bar Chart (July 2026)",
                    "period": 86400,
                    "stat": "Maximum"
                }
            }
        ]
    }
    return json.dumps(dashboard_body)

def deploy_dashboards():
    print("==========================================================================")
    print("🚀 KHỞI TẠO & CẬP NHẬT 2 CLOUDWATCH DASHBOARDS DÙNG METRIC NATIVE AWS/BILLING")
    print("==========================================================================")
    
    try:
        cw = boto3.client("cloudwatch", region_name=REGION)
        
        # 1. Deploy Dashboard 1: Budget-Cost-By-Region
        name_region = "Budget-Cost-By-Region"
        body_region = build_region_dashboard_json()
        cw.put_dashboard(DashboardName=name_region, DashboardBody=body_region)
        print(f"✅ Dashboard 1 thành công: '{name_region}'")
        print(f"   📌 Namespace: AWS/Billing | Metric: EstimatedCharges")
        print(f"   📅 Timeframe: 01/07/2026 - 31/07/2026")
        print(f"   🔗 URL: https://console.aws.amazon.com/cloudwatch/home?region={REGION}#dashboards:name={name_region}")

        # 2. Deploy Dashboard 2: Budget-Cost-By-Service
        name_service = "Budget-Cost-By-Service"
        body_service = build_service_dashboard_json()
        cw.put_dashboard(DashboardName=name_service, DashboardBody=body_service)
        print(f"✅ Dashboard 2 thành công: '{name_service}'")
        print(f"   📌 Namespace: AWS/Billing | Metric: EstimatedCharges")
        print(f"   📅 Timeframe: 01/07/2026 - 31/07/2026")
        print(f"   🔗 URL: https://console.aws.amazon.com/cloudwatch/home?region={REGION}#dashboards:name={name_service}")

        print("--------------------------------------------------------------------------")
        print("🎉 Hoàn tất 100%! Đã chuyển toàn bộ 2 Dashboard sang dùng metric AWS/Billing gốc.")
        print("==========================================================================")

    except Exception as e:
        print(f"❌ Lỗi khi cập nhật CloudWatch Dashboards: {e}")
        sys.exit(1)

if __name__ == "__main__":
    deploy_dashboards()
