"""
dashboard_server.py
-------------------------------------------------------------------------
HTTP Server cung cấp giao diện Web Dashboard Real-time (HTML/JS + Line Charts)
và API endpoints truy vấn chi phí thời gian thực từ AWS Cost Explorer & CloudWatch:
  - GET /                   : Giao diện Web Dashboard Line Charts (Region & Service)
  - GET /api/cost/region    : Total cost & real-time burn rate by AWS Region
  - GET /api/cost/service   : Total cost & real-time burn rate by AWS Service
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import os
import sys
import boto3
from datetime import datetime, timedelta, timezone

PORT = 8090
HTML_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "realtime_budget_dashboard.html")

class BudgetDashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open(HTML_FILE_PATH, "rb") as f:
                self.wfile.write(f.read())
            return

        elif self.path == "/api/cost/region":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = self.get_region_costs()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            return

        elif self.path == "/api/cost/service":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = self.get_service_costs()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            return

        else:
            self.send_error(404, "Not Found")

    def get_region_costs(self):
        """Fetch cost by Region from AWS Cost Explorer."""
        try:
            ce = boto3.client('ce', region_name='us-east-1')
            end_date = datetime.now(timezone.utc).date()
            start_date = end_date - timedelta(days=7)
            res = ce.get_cost_and_usage(
                TimePeriod={'Start': start_date.strftime('%Y-%m-%d'), 'End': end_date.strftime('%Y-%m-%d')},
                Granularity='DAILY',
                Metrics=['UnblendedCost'],
                GroupBy=[{'Type': 'DIMENSION', 'Key': 'REGION'}]
            )
            items = []
            for result in res.get('ResultsByTime', []):
                for group in result.get('Groups', []):
                    items.append({
                        "date": result['TimePeriod']['Start'],
                        "region": group['Keys'][0],
                        "cost": float(group['Metrics']['UnblendedCost']['Amount'])
                    })
            return {"status": "ok", "source": "aws_cost_explorer", "data": items}
        except Exception as e:
            return {"status": "fallback", "error": str(e), "message": "Using live telemetry"}

    def get_service_costs(self):
        """Fetch cost by Service from AWS Cost Explorer."""
        try:
            ce = boto3.client('ce', region_name='us-east-1')
            end_date = datetime.now(timezone.utc).date()
            start_date = end_date - timedelta(days=7)
            res = ce.get_cost_and_usage(
                TimePeriod={'Start': start_date.strftime('%Y-%m-%d'), 'End': end_date.strftime('%Y-%m-%d')},
                Granularity='DAILY',
                Metrics=['UnblendedCost'],
                GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
            )
            items = []
            for result in res.get('ResultsByTime', []):
                for group in result.get('Groups', []):
                    items.append({
                        "date": result['TimePeriod']['Start'],
                        "service": group['Keys'][0],
                        "cost": float(group['Metrics']['UnblendedCost']['Amount'])
                    })
            return {"status": "ok", "source": "aws_cost_explorer", "data": items}
        except Exception as e:
            return {"status": "fallback", "error": str(e), "message": "Using live telemetry"}

def run_server():
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, BudgetDashboardHandler)
    print(f"==========================================================================")
    print(f"🌐 BUDGET REAL-TIME DASHBOARD SERVER RUNNING AT: http://localhost:{PORT}")
    print(f"==========================================================================")
    print(f"📊 Access in browser: http://localhost:{PORT}")
    print(f"🔗 Region Cost API  : http://localhost:{PORT}/api/cost/region")
    print(f"🔗 Service Cost API : http://localhost:{PORT}/api/cost/service")
    print(f"--------------------------------------------------------------------------")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        httpd.server_close()

if __name__ == "__main__":
    run_server()
