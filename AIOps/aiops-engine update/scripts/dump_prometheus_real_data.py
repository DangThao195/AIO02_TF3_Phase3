import os
import sys
import logging
import pandas as pd
from datetime import datetime

# Setup sys.path guard
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from train_anomaly_model_eks import fetch_metrics_from_prometheus, SERVICES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AIOpsEngine.DumpRealData")

def main():
    logger.info("======================================================================")
    logger.info(">>> START DUMPING REAL PROMETHEUS TELEMETRY DATA (7 DAYS)")
    logger.info("======================================================================")
    
    engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(engine_dir, "datametric")
    os.makedirs(output_dir, exist_ok=True)
    
    summary = []
    
    for service in SERVICES:
        logger.info(f"Fetching real Prometheus metrics for: {service} (7 days)...")
        df_raw = fetch_metrics_from_prometheus(service, duration_days=7)
        
        if df_raw.empty:
            logger.warning(f"❌ No real Prometheus data returned for {service}.")
            summary.append({"service": service, "rows": 0, "status": "FAILED (Empty)", "path": "N/A"})
        else:
            output_file = os.path.join(output_dir, f"{service}_real_7d.csv")
            df_raw.to_csv(output_file, index=False)
            start_ts = df_raw["timestamp"].min()
            end_ts = df_raw["timestamp"].max()
            logger.info(f"✅ Successfully saved {len(df_raw)} rows for {service} to {output_file} ({start_ts} -> {end_ts})")
            summary.append({
                "service": service,
                "rows": len(df_raw),
                "status": "SUCCESS",
                "date_range": f"{start_ts} to {end_ts}",
                "path": output_file
            })
            
    logger.info("======================================================================")
    logger.info("SUMMARY RESULTS:")
    for item in summary:
        logger.info(f" - {item['service']}: {item['status']} | Rows: {item.get('rows', 0)} | Path: {item.get('path')}")
    logger.info("======================================================================")

if __name__ == "__main__":
    main()
