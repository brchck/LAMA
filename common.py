import logging
import subprocess
import shutil
import SimpleITK as sitk
import os
import psutil
import sys
import numpy as np

LOG_FILE = 'LAMA.log'
LOG_MODE = logging.DEBUG


def write_array(array, path, compressed=True):
    """
    Write a numpy array to and image file using SimpleITK
    """
    sitk.WriteImage(sitk.GetImageFromArray(array), path, compressed)


def img_path_to_array(img_path):
    if os.path.isfile(img_path):
        try:
            img = sitk.ReadImage(img_path)

        except RuntimeError:
            print "Simple ITK cannot read {}".format(img_path)
            return None
        else:
            array = sitk.GetArrayFromImage(img)
            return array
    else:
        print '{} is not a real path'.format(img_path)
        return None


def git_log():

    # switch working dir to this module's location
    orig_wd = os.getcwd()
    module_dir = os.path.dirname(os.path.realpath(__file__))
    os.chdir(module_dir)

    try:
        git_log = subprocess.check_output(['git', 'log', '-n', '1'])
        git_commit = git_log.splitlines()[0]
        git_branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
    except subprocess.CalledProcessError:
        git_commit = "Git commit info not available"
        git_branch = "Git branch not available"

    message = "git branch: {}. git {}: ".format(git_branch.strip(), git_commit.strip())

    # back to original working dir
    os.chdir(orig_wd)
    return message

def init_logging(logpath):

    if os.path.exists(logpath):  # Create new log file if one already exists
        i = 1
        while True:
            path, ext = os.path.splitext(logpath)
            newname = path + '_' + str(i)
            new_logpath = newname + ext
            if not os.path.exists(new_logpath):
                logpath = new_logpath
                break
            i += 1

    logging.basicConfig(filename=logpath, level=LOG_MODE,
                        format='%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %I:%M:%S %p')

    stdout_log = logging.StreamHandler(sys.stdout)
    logging.getLogger().addHandler(stdout_log)

def mkdir_force(dir_):
    if os.path.isdir(dir_):
        shutil.rmtree(dir_)
    os.mkdir(dir_)

def mkdir_if_not_exists(dir_):
    if not os.path.exists(dir_):
        os.makedirs(dir_)


def GetFilePaths(folder, extension_tuple=('.nrrd', '.tiff', '.tif', '.nii', '.bmp', 'jpg', 'mnc', 'vtk', 'bin'), pattern=None):
    """
    Test whether input is a folder or a file. If a file or list, return it.
    If a dir, return all images within that directory.
    Optionally test for a pattern to sarch for in the filenames
    """
    if not os.path.isdir(folder):
        return False
    else:
        paths = []
        for root, _, files in os.walk(folder):
            for filename in files:
                if filename.lower().endswith(extension_tuple):
                    if pattern:
                        if pattern and pattern not in filename:
                            continue
                    #paths.append(os.path.abspath(os.path.join(root, filename))) #Broken on shared drive
                    paths.append(os.path.join(root, filename))
        return paths


def check_config_entry_path(dict_, key):
    try:
        value = dict_[key]
    except KeyError:
        raise Exception("'{} not specified in config file".format(key))
    else:
        if not os.path.isdir(value):
            raise OSError("{} is not a correct directory".format(value))


def print_memory(fn):
    def wrapper(*args, **kwargs):
        process = psutil.Process(os.getpid())
        start_rss, start_vms = process.get_memory_info()
        try:
            return fn(*args, **kwargs)
        finally:
            end_rss, end_vms = process.get_memory_info()
            print((end_rss - start_rss), (end_vms - start_vms))
    return wrapper


def get_inputs_from_file_list(file_list_path, config_dir):
    paths = []
    with open(file_list_path, 'r') as reader:
        root = reader.next().strip()
        for line in reader:
            base = line.strip()
            if base:  # miss out trailing newlines at EOF
                path = os.path.join(config_dir, root, base)
                paths.append(path)
    return paths

def Average(img_dirOrList, search_subdirs=True):
    '''
    Create an average volume from multiple volumes
    @return: sitk Image
    '''
    images = []
    if isinstance(img_dirOrList, basestring):
        images = GetFilePaths(img_dirOrList)
    else:
        images = img_dirOrList

    #sum all images together
    summed = sitk.GetArrayFromImage(sitk.ReadImage(images[0]))
    for image in images[1:]:  # Ommit the first as we have that already
        np_array = sitk.GetArrayFromImage(sitk.ReadImage(image))
        try:
            summed += np_array
        except ValueError as e:
            print "Numpy can't average this volume {0}".format(image)

    #Now make average. Do it in numpy as I know how
    summed /= len(images)
    avg_img = sitk.GetImageFromArray(summed)
    return avg_img


def subsample(array, chunk_size, mask=False):
    """
    Parameters
    ----------
    array: numpy.ndarray
    """

    shape = array.shape
    i = 0
    subsampled_array = []
    out_shape = [0, 0, 0]  # zyx
    for z in range(0, shape[0] - chunk_size, chunk_size):
        out_shape[0] += 1
        for y in range(0, shape[1] - chunk_size, chunk_size):
            if z == 0:
                out_shape[1] += 1
            for x in range(0, shape[2] - chunk_size, chunk_size):
                if z == 0 and y == 0:
                    out_shape[2] += 1
                mask_region = array[z: z + chunk_size, y: y + chunk_size, x: x + chunk_size]
                if mask:  # If any in the cube is a mask element, make the whole cube a mask
                    if np.any(mask_region):
                        subsampled_array.insert(i, 1)
                    else:
                        subsampled_array.insert(i, 0)
                else:
                    subsampled_array.insert(i, np.mean(mask_region))
                i += 1
    if mask:
        return np.array(subsampled_array).astype(np.bool).reshape(out_shape)
    else:
        return np.array(subsampled_array).reshape(out_shape)
