import urllib.request

url = "http://k8s-techxtf3-aiopseng-ac927793fa-767978147.ap-southeast-1.elb.amazonaws.com/remediation/approve"
try:
    req = urllib.request.Request(url, method="POST", data=b'{}', headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        print("Response status:", resp.status)
        print("Response body:", resp.read().decode("utf-8"))
except Exception as e:
    print("Result:", e)
