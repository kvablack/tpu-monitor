#!/usr/bin/env python3

import os
import asyncio


async def get_size(path: str) -> str:
    """
    Asynchronously get the size of a directory using `du`.
    """
    process = await asyncio.create_subprocess_exec(
        "du", "-sh", path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    return stdout.decode().strip()


def size_to_bytes(size: str) -> int:
    """
    Convert a human-readable size string (like "2K", "3M", "4G") to bytes.
    """
    size = size.upper()
    if "K" in size:
        return int(float(size.replace("K", "")) * 1024)
    if "M" in size:
        return int(float(size.replace("M", "")) * 1024**2)
    if "G" in size:
        return int(float(size.replace("G", "")) * 1024**3)
    if "T" in size:
        return int(float(size.replace("T", "")) * 1024**4)
    return int(size)


async def async_get_sorted_sizes(base_path: str) -> list:
    """
    Asynchronously get sizes of all subdirectories under `base_path`
        :return a list of tuples (size, path) sorted by size
    """
    # Get all subdirectories under the base_path
    directories = [
        dir_ for dir_ in os.listdir(base_path)
        if os.path.isdir(os.path.join(base_path, dir_)) and
        not dir_.startswith('.')
    ]

    if not directories:
        return []

    paths = [os.path.join(base_path, dir_) for dir_ in directories]

    # Gather sizes asynchronously
    sizes = await asyncio.gather(*(get_size(path) for path in paths))

    # Split size from path and sort
    sorted_sizes = sorted(
        [(size.split("\t")[0], size.split("\t")[1]) for size in sizes],
        key=lambda x: size_to_bytes(x[0]),
        reverse=True
    )
    return sorted_sizes


def main():
    path = os.path.expanduser('~/')
    sorted_sizes = asyncio.run(async_get_sorted_sizes(path))
    for size, path in sorted_sizes:
        print(f"{size} - {path}")
    print(f"Total: {len(sorted_sizes)}")


if __name__ == "__main__":
    main()
