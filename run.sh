(trap 'kill 0' INT TERM; python monitor.py & python -m http.server -d serve)