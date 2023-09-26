# tpu-monitor

## Installation

```
pip install -r requirements.txt
```

## Usage
```
./run.sh
```

All this does is run:
- `python monitor.py`, which periodically writes to `serve/index.html`
- `python -m http.server -d serve`, which serves the contents of `serve/` on port `8000`

Open dashboard on: http://0.0.0.0:8000/

Optionally, you can specify which TPU by editing the `config/vms.csv` file, and parse the file path to `monitor.py` as an argument.
