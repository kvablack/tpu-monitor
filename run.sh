(
    trap 'kill 0' INT TERM; python monitor.py --all_zones &
    python -m http.server -d serve
)
