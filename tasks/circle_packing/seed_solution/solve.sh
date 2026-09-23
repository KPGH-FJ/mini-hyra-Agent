#!/bin/bash
cd "$(dirname "$0")"
mkdir -p .run
python3 pack.py > solution.json
