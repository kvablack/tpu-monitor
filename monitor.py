from dataclasses import dataclass
import asyncio
import csv
import datetime
from typing import Dict, List, Optional
import jinja2
import time

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
    last_updated: datetime.datetime


@dataclass
class VM:
    name: str
    zone: str
    type: str
    usage: Optional[Dict[int, Chip]] = None

    async def update_usage(self):
        print(f"Updating {self.name}")
        async with asyncio.timeout(TIMEOUT):
            proc = await asyncio.create_subprocess_shell(
                TPU_USAGE_CMD.format(name=self.name, zone=self.zone),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

        if proc.returncode != 0 and not stdout:
            raise Exception(
                f"Error running command:\n\n{stderr.decode()}\n\n{stdout.decode()}"
            )

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

        new_usage = {chip: Chip(None, datetime.datetime.now()) for chip in chips}

        # in case of no lsof output
        if line:
            # the remaining lines are the lsof output
            for line in out:
                if not line:
                    continue
                user = line.split()[2]
                chip = int(line.split()[-1][len("/dev/accel") :])
                if chip not in new_usage:
                    raise Exception(
                        f"Unexpected chip: {line.split()[-1][len('/dev/accel'):]}\n\n{stdout.decode()}"
                    )
                if new_usage[chip].user is not None and new_usage[chip].user != user:
                    raise Exception(
                        f"Multiple users on same chip: found {user} and {new_usage[chip].user} on chip {chip}\n\n{stdout.decode()}"
                    )
                new_usage[chip].user = user

        if self.usage:
            # update timestamps only if user has changed
            for chip in new_usage:
                if new_usage[chip].user != self.usage[chip].user:
                    self.usage[chip] = new_usage[chip]
        else:
            self.usage = new_usage


async def main(vms: List[VM]):
    while True:
        results = await asyncio.gather(
            *[vm.update_usage() for vm in vms],
            return_exceptions=True,
        )

        for vm, result in zip(vms, results):
            if isinstance(result, Exception):
                print(f"Error updating {vm.name}: {result}")
                vm.usage = None
            else:
                print(f"Successfully updated {vm.name}")

        vm_types = sorted(set(vm.type for vm in vms))
        vm_groups = {
            vm_type: [vm for vm in vms if vm.type == vm_type] for vm_type in vm_types
        }

        template_loader = jinja2.FileSystemLoader(searchpath="./templates")
        template_env = jinja2.Environment(loader=template_loader)
        template = template_env.get_template("index.html")
        with open("serve/index.html", "w") as f:
            f.write(template.render(vm_groups=vm_groups))

        await asyncio.sleep(RUN_FREQUENCY)


if __name__ == "__main__":
    # get vm info from csv
    with open("config/vms.csv") as f:
        reader = csv.DictReader(f)
        vms = [VM(**row) for row in reader]

    asyncio.run(main(vms))