import pandas as pd
import os

# Create datametric dir if not exists
os.makedirs("datametric", exist_ok=True)

# Read the last few rows of frontend_train.csv to copy structure
train_path = "datametric/frontend_train.csv"
if not os.path.exists(train_path):
    train_path = "aiops-engine/datametric/frontend_train.csv"

df = pd.read_csv(train_path)

# Take the last row as a base template
last_row = df.iloc[-1].copy()

# Modify metrics to inject a massive anomaly
# For example: extremely high latency, high CPU, high error rate
last_row["timestamp"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
last_row["error_rate"] = 15.0
last_row["error_ratio"] = 5.0
last_row["latency_p90"] = 1200.0  # 1.2s latency
last_row["latency_deviation"] = 35.0  # massive deviation
last_row["cpu_usage"] = 0.98  # 98% CPU
last_row["cpu_per_rps"] = 0.5
last_row["label"] = 0  # Anomaly label

# Create a DataFrame containing 12 rows of normal history, and the last row as anomalous
df_fake = df.tail(12).copy()
df_fake.iloc[-1] = last_row

# Save as fake_frontend.csv
output_path = "datametric/fake_frontend.csv"
df_fake.to_csv(output_path, index=False)
print(f"Successfully generated {output_path} with injected anomalies!")
