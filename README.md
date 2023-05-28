# tpu-monitor

## Installation
Requires Python >= 3.11.

```
pip install -r requirements.txt
```

## Usage
```
./run.sh
```

All this does is run:
- `python monitor.py`, which periodically writes to `serve/index.html`
- `python -m http.server -d serve`, which serves the contents of `serve/` on port 8000