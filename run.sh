#!/usr/bin/env bash
source venv311/bin/activate
# quart -A pytrace/app run
python -m hypercorn pytrace/app


