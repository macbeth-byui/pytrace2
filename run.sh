#!/usr/bin/env bash
source venv/bin/activate
# quart -A pytrace/app run
hypercorn pytrace/app


