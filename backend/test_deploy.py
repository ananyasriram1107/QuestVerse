"""
Deployment-readiness checks: CORS, configuration through environment variables, and that the
service starts and answers health checks with no Ollama and a brand-new database folder.

Same style as the other test files (plain asserts, run with `python test_deploy.py`). The
end-to-end checks start the app in a fresh Python process so the environment variables really
are read at import time, the way they are on Render.
"""

import json
import os
import subprocess
import sys
import tempfile

import cors_config

HERE = os.path.dirname(os.path.abspath(__file__))


def test_origins_come_from_frontend_url_and_wildcards_are_refused():
    got = cors_config.allowed_origins("https://questverse.vercel.app/, https://preview-1.vercel.app ,*, javascript:alert(1), https://x.com/path",
                                      "production")
    assert got == ["https://questverse.vercel.app", "https://preview-1.vercel.app"]
    assert "*" not in cors_config.allowed_origins("*", "development")


def test_localhost_is_allowed_for_development_but_not_in_production():
    dev = cors_config.allowed_origins("https://app.example.com", "development")
    assert "http://localhost:5173" in dev and "https://app.example.com" in dev
    prod = cors_config.allowed_origins("https://app.example.com", "production")
    assert prod == ["https://app.example.com"]
    assert cors_config.allowed_origins(None, "production") == [], "unconfigured production trusts no browser origin"
    assert cors_config.allowed_origins("https://a.com,https://a.com", "production") == ["https://a.com"], "no duplicates"


def test_production_service_starts_without_ollama_and_with_a_new_database_folder():
    data_dir = os.path.join(tempfile.mkdtemp(), "not", "created", "yet")
    db_path = os.path.join(data_dir, "questverse.db")
    script = r'''
import json, os, sys
from fastapi.testclient import TestClient
import main

out = {}
with TestClient(main.app) as client:                       # runs the startup hooks too
    out["health"] = client.get("/health").status_code
    pre = lambda origin: client.options("/auth/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                                                 "Access-Control-Request-Headers": "content-type,authorization"})
    ok = pre("https://questverse.vercel.app")
    out["cors_allowed"] = ok.headers.get("access-control-allow-origin")
    out["cors_localhost"] = pre("http://localhost:5173").headers.get("access-control-allow-origin")
    out["cors_evil"] = pre("https://evil.example.com").headers.get("access-control-allow-origin")
    out["cors_credentials"] = ok.headers.get("access-control-allow-credentials")
    out["no_token"] = client.get("/progress/me?student_id=x").status_code
    reg = client.post("/auth/register", json={"username": "deploycheck", "password": "a long password"}).json()
    headers = {"Authorization": "Bearer " + reg["token"]}
    start = client.get("/question/first?courseId=os&mode=mcq&student_id=u%d.human" % reg["user"]["id"], headers=headers).json()
    hint = client.post("/hint/ai", headers=headers, json={"session_id": start["session_id"], "student_id": "u%d.human" % reg["user"]["id"],
                                                          "question_id": start["id"]})
    out["hint_status"] = hint.status_code
    out["hint_detail"] = hint.json().get("detail")
    out["game_answer_status"] = client.post("/answer", headers=headers, json={
        "session_id": start["session_id"], "student_id": "u%d.human" % reg["user"]["id"], "question_id": start["id"], "answer": "x"}).status_code
out["db_exists"] = os.path.exists(os.environ["QUESTVERSE_DB"])
print("RESULT" + json.dumps(out))
'''
    env = {**os.environ, "QUESTVERSE_ENV": "production", "FRONTEND_URL": "https://questverse.vercel.app",
           "QUESTVERSE_DB": db_path, "OLLAMA_HOST": "http://127.0.0.1:9", "PYTHONIOENCODING": "utf-8"}
    run = subprocess.run([sys.executable, "-c", script], cwd=HERE, env=env, capture_output=True, text=True, timeout=120)
    line = next((l for l in run.stdout.splitlines() if l.startswith("RESULT")), None)
    assert line, f"service did not start:\n{run.stdout[-800:]}\n{run.stderr[-1500:]}"
    out = json.loads(line[len("RESULT"):])
    assert out["health"] == 200, "health must not depend on Ollama"
    assert out["cors_allowed"] == "https://questverse.vercel.app", out
    assert out["cors_localhost"] is None and out["cors_evil"] is None, "production only trusts FRONTEND_URL"
    assert out["cors_credentials"] is None, "tokens, not cookies"
    assert out["no_token"] == 401
    assert out["hint_status"] == 503 and "Ollama" in out["hint_detail"], "no fake hint when Ollama is missing"
    assert out["game_answer_status"] == 200, "the game itself needs no Ollama"
    assert out["db_exists"], "the database folder is created on first start"


def test_localhost_cors_still_works_in_development():
    script = r'''
import json
from fastapi.testclient import TestClient
import main
c = TestClient(main.app)
r = c.options("/auth/login", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
print("RESULT" + json.dumps({"dev": r.headers.get("access-control-allow-origin")}))
'''
    env = {k: v for k, v in os.environ.items() if k not in ("QUESTVERSE_ENV", "FRONTEND_URL")}
    env["QUESTVERSE_DB"] = os.path.join(tempfile.mkdtemp(), "dev.db")
    run = subprocess.run([sys.executable, "-c", script], cwd=HERE, env=env, capture_output=True, text=True, timeout=120)
    line = next((l for l in run.stdout.splitlines() if l.startswith("RESULT")), None)
    assert line and json.loads(line[6:])["dev"] == "http://localhost:5173", run.stderr[-800:]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} deployment tests passed")
    raise SystemExit(1 if failed else 0)
