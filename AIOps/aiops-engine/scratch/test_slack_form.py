import requests
import json

url = "http://k8s-techxtf3-aiopseng-ac927793fa-767978147.ap-southeast-1.elb.amazonaws.com/remediation/approve"
payload_data = {
    "type": "block_actions",
    "actions": [
        {"action_id": "reject_INC-ML-1784904967", "value": "reject"}
    ]
}

res = requests.post(url, data={"payload": json.dumps(payload_data)})
print("HTTP Status Code:", res.status_code)
print("Response Body:", res.content.decode("utf-8"))
