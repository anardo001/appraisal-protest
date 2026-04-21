
#!/usr/bin/env python3
"""
deploy_render.py — Create Render services via API
Creates:
  1. appraisal-protest-api  (Python web service, FastAPI + Uvicorn)
  2. appraisal-protest-ui   (Static site, Vite)
"""
import sys, json
import urllib.request, urllib.error

RENDER_API_KEY = "rnd_MltibtALts4ufPVvuhZEvUwoHmUp"
OWNER_ID       = "tea-d7jbnav7f7vs73e9khag"
REPO           = "https://github.com/anardo001/appraisal-protest"
BRANCH         = "master"
BASE_URL       = "https://api.render.com/v1"

def api_post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {RENDER_API_KEY}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code}: {body}")
        return None, e.code

# 1. Create FastAPI backend
print("Creating FastAPI backend service...")
backend_payload = {
    "type": "web_service",
    "name": "appraisal-protest-api",
    "ownerId": OWNER_ID,
    "repo": REPO,
    "branch": BRANCH,
    "rootDir": "backend",
    "serviceDetails": {
        "runtime": "python",
        "plan": "free",
        "region": "oregon",
        "envSpecificDetails": {
            "buildCommand": "pip install fastapi uvicorn fpdf2",
            "startCommand": "uvicorn main:app --host 0.0.0.0 --port $PORT"
        },
        "envVars": [
            {"key": "DB_PATH",         "value": "/data/dcad2026.db"},
            {"key": "PYTHON_VERSION",  "value": "3.12.0"}
        ]
    }
}
result, status = api_post("/services", backend_payload)
if result:
    svc = result.get("service", result)
    backend_id  = svc.get("id", "")
    backend_url = svc.get("serviceDetails", {}).get("url", "pending")
    print(f"Backend created: {backend_id}")
    print(f"Backend URL:     {backend_url}")
else:
    print(f"Backend creation failed ({status}). Exiting.")
    sys.exit(1)

# 2. Create Vite static site
print("\nCreating Vite static frontend...")
frontend_payload = {
    "type": "static_site",
    "name": "appraisal-protest-ui",
    "ownerId": OWNER_ID,
    "repo": REPO,
    "branch": BRANCH,
    "rootDir": "frontend-vite",
    "serviceDetails": {
        "buildCommand": "npm install && npm run build",
        "publishPath":  "dist",
        "envVars": [
            {"key": "VITE_API_URL", "value": f"https://appraisal-protest-api.onrender.com"}
        ],
        "routes": [
            {"type": "rewrite", "source": "/*", "destination": "/index.html"}
        ]
    }
}
result, status = api_post("/services", frontend_payload)
if result:
    svc = result.get("service", result)
    frontend_id  = svc.get("id", "")
    frontend_url = svc.get("serviceDetails", {}).get("url", "pending")
    print(f"Frontend created: {frontend_id}")
    print(f"Frontend URL:     {frontend_url}")
else:
    print(f"Frontend creation failed ({status}).")
    sys.exit(1)

print("\nDone. Both services created on Render.")
print("Note: Initial deploy will take 3-5 minutes to build.")
print(f"Monitor at: https://dashboard.render.com/")
