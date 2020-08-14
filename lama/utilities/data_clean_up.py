"""
LAMA produces lots of data. Sometimes we can get rid of much of it afterwrads.
This script removes folders specified in a config file.

This is a work in progress


example yaml config.
This will delete all folders named 'resolution_images'.
And will delete all contents of registraitons except folder named 'similarity'
--------------------
folders_to_rm:
  resolution_images: []
  registrations: [similarity]

--------------------

python3 data_clean_up.py config root_dir

This will recursively search directories and delete any folder called in the list
"""

from pathlib import Path
import shutil
import yaml
from typing import Iterable


def is_subseq(x: Iterable, y: Iterable) -> bool:
    """
    Check whether x is within y.

    For example
    registrations/deformable is in output/registration/deformable/192_12

    """
    it = iter(y)
    return all(c in it for c in x)


def rm_by_name(root: Path, name: str, to_keep):
    """
    Remove directories. If any path or part path is in to keep, delete the rest of the folder put keep that one.
    """
    dirs = root.glob(f'**/{name}') # Get all matching directories

    for d in dirs:

        subfolders_to_keep = []

        if not d.is_dir():
            continue

        for subdir in d.iterdir():
            if not subdir.is_dir():
                continue

            for subseq in to_keep:

                if is_subseq(Path(subseq).parts, subdir.parts):
                    print(f'{subdir} is a subseq of {subdir}')
                    subfolders_to_keep.append(subdir)

        if not subfolders_to_keep:
            shutil.rmtree(d)
        else:
            for subdir in d.iterdir():
                if subdir not in subfolders_to_keep:
                    shutil.rmtree(subdir)


def run(config_path: str, root_dir: Path):

    with open(config_path) as fh:
        config = yaml.load(fh)
    print(f"deleting {config['folders_to_rm']}")

    for dir_, subdirs_to_keep in config['folders_to_rm'].items():
        rm_by_name(root_dir, dir_, subdirs_to_keep)


if __name__ == '__main__':
    import sys
    config_path = sys.argv[1]
    root_dir = sys.argv[2]
    run(config_path, Path(root_dir))
