"""Start the Workbench BFF: python run.py [--port 8080]"""
import argparse

import uvicorn

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    a = p.parse_args()
    uvicorn.run("app.main:app", host=a.host, port=a.port)
