#!/bin/bash
cd "$(dirname "$0")"
mkdir -p .run
python3 model.py > solution.json
