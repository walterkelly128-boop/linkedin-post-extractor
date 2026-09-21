#!/usr/bin/env python3
"""Standalone entrypoint for running the Web Dashboard."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.web:app", host="0.0.0.0", port=8000, reload=False)
