#!/bin/bash
cd "$(dirname "$0")"
nohup .venv/bin/python -W ignore::SyntaxWarning -m radio_monitor.main > /dev/null 2>&1 &
echo $! > radio-monitor.pid
echo "Started (PID $!)"
