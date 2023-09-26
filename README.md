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


**(Add-on) Monitor custom TPU VMs**

Optionally, you can specify which TPU by editing the `config/vms.csv` file, and parse the file path to `monitor.py` as an argument.

**(Add-on) Monitor custom filestores**

In the `config/config.yaml` file, you can specify the list of filestore paths you want to monitor. e.g. `"filestore_paths": ["/mnt/nfs1", "/mnt/nfs2"]`

To mount the filestore (refer to [this](https://cloud.google.com/filestore/docs/mounting-fileshares)), you can run the following:
```bash
sudo mkdir -p /mnt/nfs1

# get the filestore IP address
gcloud filestore instances list

# mount the remote filestore to the local directory
# TODO: change the IP address and filestore path
sudo mount -o rw,intr 10.244.23.202:/nfs1 /mnt/nfs1
```
