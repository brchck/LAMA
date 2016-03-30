#!/usr/bin/env python


"""
Given a sequence of deformation fields, generate a mean deformation field and jacobian determinant file
"""

import common
import logging
import os
import sys
from os.path import join, basename
import subprocess
import shutil
import SimpleITK as sitk
import numpy as np
import gc


ELX_TFORM_NAME =  'TransformParameters.0.txt'
# ELX_TFORM_NAME = 'meanTransformParameter.txt'


def generate_deformation_fields(registration_dirs, deformation_dir, jacobian_dir, threads, filetype='nrrd'):
    """
    Run transformix on the specified registration stage to generate deformation fields and spatial jacobians

    Parameters
    ----------
    registration_dirs: list
        registration directories in order that they were registered
    """
    logging.info('### Generating deformation files ###')
    logging.info('Generating deformation fields from following reg_stages {}'.format('\n'.join(registration_dirs)))

    first_reg_dir = registration_dirs[0]

    specimen_list = [x for x in os.listdir(first_reg_dir) if os.path.isdir(join(first_reg_dir, x))]

    for specimen_id in specimen_list:
        transform_params = []
        # Get the transform parameters for the subsequent registrations
        for i, reg_dir in enumerate(registration_dirs):

            single_reg_dir = join(reg_dir, specimen_id)

            elx_tform_file = join(single_reg_dir, ELX_TFORM_NAME)
            if not os.path.isfile(elx_tform_file):
                sys.exit("### Error. Cannot find elastix transform parameter file: {}".format(elx_tform_file))

            transform_params.append(elx_tform_file)

        modfy_tforms(transform_params)
        get_deformations(transform_params[-1], deformation_dir, jacobian_dir, filetype, specimen_id, threads)


def modfy_tforms(tforms):
    """
    Add the initial paramter file paths to the tform files
    :return:
    """
    for i, tp in enumerate(tforms[1:]):
        initial_tp = tforms[i]
        with open(tp, 'rb') as fh:
            lines = []
            for line in fh:
                if line.startswith('(InitialTransformParametersFileName'):
                    continue
                lines.append(line)
        previous_tp_str = '(InitialTransformParametersFileName "{}")'.format(initial_tp)
        lines.insert(0, previous_tp_str + '\n')
        with open(tp, 'wb') as wh:
            for line in lines:
                wh.write(line)


def get_deformations(tform, deformation_dir, jacobian_dir, filetype, specimen_id, threads):
    """
    """
    temp_def_dir = join(deformation_dir, 'temp_deformation')
    common.mkdir_if_not_exists(temp_def_dir)

    cmd = ['transformix',
           '-out', temp_def_dir,
           '-def', 'all',
           '-jac', 'all',
           '-tp', tform,
           'threads', threads
           ]

    try:
        output = subprocess.check_output(cmd)
    except Exception as e:  # Can't seem to log CalledProcessError
        logging.warn('transformix failed {}'.format(', '.join(cmd)))
        sys.exit('### Transformix failed ###\nError message: {}\nelastix command:{}'.format(e, cmd))
    else:
        # read in and sum up the deformation fields
        deformation_out = join(temp_def_dir, 'deformationField.{}'.format(filetype))
        jacobian_out = join(temp_def_dir, 'spatialJacobian.{}'.format(filetype))
        # rename and move output
        new_def = join(deformation_dir, specimen_id + '.' + filetype)
        shutil.move(deformation_out, new_def)

        new_jac = join(jacobian_dir, specimen_id + '.' + filetype)
        shutil.move(jacobian_out, new_jac)

        shutil.rmtree(temp_def_dir)


    logging.info('Finished generating deformation fields')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser("Generate deformation fields and spatial jacobians from elastix registration")
    parser.add_argument('-r', '--reg_dirs', dest='reg_dirs', help='Series of registration directories', required=True, nargs='*')
    parser.add_argument('-d', '--def_out', dest='def_out', help='folder to put deformations in', required=True)
    parser.add_argument('-j', '--jac_out', dest='jac_out', help='folder to put jacobians in', required=True)
    parser.add_argument('-t', '--threads', dest='threads', help='Numberof threads to use', required=True, type=int)
    args = parser.parse_args()

    generate_deformation_fields([os.path.abspath(x) for x in args.reg_dirs],
                                os.path.abspath(args.def_out),
                                os.path.abspath(args.jac_out),
                                args.threads)
