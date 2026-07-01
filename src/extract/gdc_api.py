import json
import sys
import urllib.error
import urllib.request

FILES_URL = "https://api.gdc.cancer.gov/files"
CASES_URL = "https://api.gdc.cancer.gov/cases"


def post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"GDC API error {e.code}: {e.read().decode()}")
