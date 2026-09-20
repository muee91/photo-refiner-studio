#!/usr/bin/env python3
from __future__ import annotations
import argparse
import http.server
import socketserver
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='Serve Photo Refiner Node Canvas locally')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    with socketserver.TCPServer(('127.0.0.1',args.port),Handler) as server:
        print(f'Photo Refiner Node Canvas: http://127.0.0.1:{args.port}/node-canvas/')
        server.serve_forever()
