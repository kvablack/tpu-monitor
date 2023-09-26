#!/usr/bin/env python3

from dataclasses import dataclass
import asyncio
import csv
import datetime
import subprocess
from typing import Dict, List, Optional, List
import argparse
import jinja2
from filestore import async_get_sorted_sizes
import yaml
import os

TPU_USAGE_CMD = "gcloud compute tpus tpu-vm ssh --zone={zone} --command='sudo ls /dev/accel*; sudo lsof -w /dev/accel*' {name}"

LSOF_COLUMN_NAMES = [
    "COMMAND",
    "PID",
    "USER",
    "FD",
    "TYPE",
    "DEVICE",
    "SIZE/OFF",
    "NODE",
    "NAME",
]

TIMEOUT = 30  # seconds

RUN_FREQUENCY = 60 * 5  # seconds


@dataclass
class Chip:
    user: Optional[str]
    last_changed: datetime.datetime


@dataclass
class VM:
    name: str
    zone: str
    type: str
    usage: Optional[Dict[int, Chip]] = None

    async def update_usage(self):
        print(f"Updating {self.name}")
        try:
            # Wrap the coroutine with asyncio.wait_for
            # NOTE: asyncio.timeout(TIMEOUT) is only supported
            # in python3.11 thus use wait_for
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_shell(
                    TPU_USAGE_CMD.format(name=self.name, zone=self.zone),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=TIMEOUT  # Set the timeout
            )
            stdout, stderr = await proc.communicate()
        except asyncio.TimeoutError:
            raise Exception(f"Command timed out after {TIMEOUT} seconds.")

        out = iter(stdout.decode().split("\n"))

        # the first n lines are the ls /dev/accel* output
        chips = set()
        while True:
            line = next(out)
            if not line.startswith("/dev/accel"):
                break
            chips.add(int(line[len("/dev/accel") :]))

        # the next line is the lsof column names
        if not chips or (line and line.split() != LSOF_COLUMN_NAMES):
            raise Exception(f"Unexpected output format:\n\n{stdout.decode()}")

        if self.usage and set(self.usage.keys()) != chips:
            raise Exception(
                f"Unexpected chips: {set(self.usage.keys())} != {chips}\n\n{stdout.decode()}"
            )

        chip_to_user: Dict[int, Optional[str]] = {
            chip: None for chip in chips
        }  # chip(int) -> user(str)

        # in case of no lsof output
        if line:
            # the remaining lines are the lsof output
            for line in out:
                if not line:
                    continue
                user = line.split()[2]
                chip = int(line.split()[-1][len("/dev/accel") :])
                if chip not in chip_to_user:
                    raise Exception(
                        f"Unexpected chip: {line.split()[-1][len('/dev/accel'):]}\n\n{stdout.decode()}"
                    )
                if chip_to_user[chip] is not None and chip_to_user[chip] != user:
                    raise Exception(
                        f"Multiple users on same chip: found {user} and {chip_to_user[chip]} on chip {chip}\n\n{stdout.decode()}"
                    )
                chip_to_user[chip] = user

        if self.usage:
            if set(chip_to_user.keys()) != set(self.usage.keys()):
                raise Exception(
                    f"Chips changed: {set(self.usage.keys())} != {set(chip_to_user.keys())}\n\n{stdout.decode()}"
                )

            # update timestamps only if user has changed
            for chip in chip_to_user:
                if chip_to_user[chip] != self.usage[chip].user:
                    self.usage[chip] = Chip(chip_to_user[chip], datetime.datetime.now(datetime.timezone.utc))
        else:
            # this is the first update
            self.usage = {
                chip: Chip(chip_to_user[chip], datetime.datetime.now(datetime.timezone.utc))
                for chip in chip_to_user
            }


def create_vms_from_all_zones() -> List[VM]:
    """
    Create VM objects for all TPU VMs in all zones.
    """
    # Get the list of all TPU locations
    cmd_locations = "gcloud compute tpus locations list"
    locations_output = subprocess.check_output(cmd_locations, shell=True).decode('utf-8')
    
    # Split the output by lines and skip the header
    locations_lines = locations_output.split("\n")[1:]
    
    # Extract the zone names from the output
    zones = [line.split()[0] for line in locations_lines if line]

    vms = []
    for zone in zones:
        # Get VMs for each zone
        cmd_vms = f"gcloud alpha compute tpus tpu-vm list --zone={zone}"
        vms_output = subprocess.check_output(cmd_vms, shell=True).decode('utf-8')
        # Split the output by lines and skip the header
        vms_lines = vms_output.split("\n")[1:]
        print(f"Getting VMs for zone {zone} with {len(vms_lines)} vms")

        # Extract the VM details and create VM objects
        for line in vms_lines:
            if line:
                parts = line.split()
                name = parts[0]
                vm_type = parts[2]
                # print(f"Creating VM object for {name}, {zone}, {vm_type}")
                vms.append(VM(name=name, zone=zone, type=vm_type))

    print("Created {} VM objects".format(len(vms)))
    return vms


class Monitor:
    def __init__(self, vms: List[VM], vm_update_freq: int, fs_update_freq: int):
        self.vms = vms
        self.vm_update_freq = vm_update_freq
        self.fs_update_freq = fs_update_freq
        self.vm_groups = None
        self.fs_results = None
        self.fs_time = datetime.datetime.now(datetime.timezone.utc)
        self.vm_time = datetime.datetime.now(datetime.timezone.utc)
    
    async def update_vms(self, vms: List[VM], vm_update_freq: int):
        """
        VM update loop.
        """
        if len(vms) == 0:
            print("WARNING! No VMs to update")
            return

        while True:
            results = await asyncio.gather(
                *[vm.update_usage() for vm in vms],
                return_exceptions=True,
            )

            for vm, result in zip(vms, results):
                if isinstance(result, Exception):
                    print(f"Error updating {vm.name}: {type(result)}: {result}")
                    vm.usage = None
                else:
                    print(f"Successfully updated {vm.name}")

            vm_types = sorted(set(vm.type for vm in vms))
            vm_groups = {
                vm_type: [vm for vm in vms if vm.type == vm_type] for vm_type in vm_types
            }
            self.vm_groups = vm_groups
            self.vm_time = datetime.datetime.now(datetime.timezone.utc)
            self.write_to_html()
            await asyncio.sleep(vm_update_freq)


    async def update_fss(self, dir_paths: List[str], fs_update_freq: int):
        """
        Filestore update loop.
        """
        if len(dir_paths) == 0:
            print("WARNING! No filestores to update")
            return

        while True:
            results = await asyncio.gather(
                *[async_get_sorted_sizes(path) for path in dir_paths],
                return_exceptions=True,
            )

            # Create a dictionary for the results
            filestore_dict = {}
            for path, result in zip(dir_paths, results):
                # Use the directory name as the key (or some other identifier)
                directory_name = os.path.basename(path)
                filestore_dict[directory_name] = result[:15]

            self.fs_results = filestore_dict
            self.fs_time = datetime.datetime.now(datetime.timezone.utc)
            self.write_to_html()
            print(f"Successfully updated filestores")
            await asyncio.sleep(fs_update_freq)


    def write_to_html(self):
        """
        Write the results to an html file.
        """
        template_loader = jinja2.FileSystemLoader(searchpath="./templates")
        temple_env = jinja2.Environment(loader=template_loader)
        template = temple_env.get_template("index.html")
        with open("serve/index.html", "w") as f:
            f.write(template.render(
                filestore_results=self.fs_results,
                vm_groups=self.vm_groups,
                vm_now=self.vm_time,
                fs_now=self.fs_time,
            ))


async def main(vms: List[VM], fss: List[str],
               vm_update_freq: int, fs_update_freq: int):
    
    monitor = Monitor(vms, vm_update_freq, fs_update_freq)
    vm_updater = asyncio.create_task(monitor.update_vms(vms, vm_update_freq))
    fs_updater = asyncio.create_task(monitor.update_fss(fss, fs_update_freq))

    # run until either vm_updater or fs_updater finishes
    await asyncio.gather(vm_updater, fs_updater)    


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="config/vms.csv")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--all_zones", action="store_true")
    parser.add_argument("--freq", default=RUN_FREQUENCY, type=int)
    args = parser.parse_args()

    if args.all_zones:
        vms = create_vms_from_all_zones()
    else:
        with open(args.csv) as f:
            reader = csv.DictReader(f)
            vms = [VM(**row) for row in reader]
            
    # read filestore paths from config
    with open(args.config) as f:
        config = yaml.safe_load(f)
        fss = config["filestore_paths"]

    asyncio.run(main(vms, fss, args.freq, args.freq))
