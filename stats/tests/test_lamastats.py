import nose
from nose.tools import assert_equals, nottest
from nose import with_setup
from staging.get_volumes_by_stage import VolumeGetter
from tempfile import NamedTemporaryFile
from stats import lama_stats
from os.path import join, realpath, dirname, basename
import os
from copy import copy
import common

"""
nose tests for lama_stats.py
These tests just test the whole pipeline with different config file options
"""

wt_staging_file = NamedTemporaryFile()
mut_staging_file = NamedTemporaryFile()


# def setup():
# 	print
# 	'setting up'
# 	with open(wt_staging_file.name, 'w') as fh:
# 		fh.write(wt_data)
#
#
# def save_mutant_file(data):
# 	with open(mut_staging_file.name, 'w') as mf:
# 		mf.write(data)
this_script_dir = dirname(realpath(__file__))
path_test_dir = 'test_data/paths_test'


def touch_files(fnames):
	for fname in fnames:
		open(fname, 'w').close()


def remove(list_, ids):
	for elem in list_:
		if common.strip_extension(basename(elem)) in ids:
			list_.remove(elem)
	return list_


def move(source_list, target_list, ids):
	for elem in source_list:
		if common.strip_extension(basename(elem)) in ids:
			target_list.append(elem)
	return target_list


wts = [
	'wt1.nnrd',
	'wt2.nrrd',
	'wt3.nrrd',
	'wt4.nrrd',
	'wt5.nrrd',
	'wt6.nrrd',
	'wt7.nrrd',
	'wt8.nrrd',
	'wt9,nrrd',
	'wt10.nrrd',
	'wt11.nrrd',
	'wt12.nrrd'
]


muts = [
	'mut1.nrrd',
	'mut2.nrrd',
	'mut3.nrrd',
	'mut4.nrrd',
	'mut5.nrrd',
	'mut6_WT.nrrd'
]

# Create some real paths with volume extensions although just empty file
@nottest
def data():
	w = [join(this_script_dir, path_test_dir, 'wt', w) for w in wts]
	m = [join(this_script_dir, path_test_dir, 'mut', m) for m in muts]
	return w, m

# touch_files(wildtypes)
# touch_files(mutants)

@nottest
def test_get_filtered_paths_use_all():
	wildtypes, mutants = data()
	wt_result, mut_result = lama_stats.get_filtered_paths(wildtypes, mutants)
	assert_equals(sorted(wt_result), sorted(wildtypes))


@nottest
def test_get_filtered_paths_add_littermates_to_baselines():
	wildtypes, mutants = data()
	littermate_ids = ['mut6', 'mut1']
	mut_expected = remove(copy(mutants), littermate_ids)
	wt_expected = move(copy(mutants), copy(wildtypes), littermate_ids)
	wt_result, mut_result = lama_stats.get_filtered_paths(wildtypes, mutants, littermate_controls=littermate_ids)
	assert_equals(sorted(wt_expected), sorted(wt_result))
	assert_equals(sorted(mut_expected), sorted(mut_result))


@nottest
def test_get_filtered_paths_add_littermates_pattern():
	wildtypes, mutants = data()
	littermate_ids = ['mut6_WT']
	wt_expected = move(mutants, wildtypes, littermate_ids)
	mut_expected = remove(mutants, littermate_ids)
	wt_result, mut_result = lama_stats.get_filtered_paths(wildtypes, mutants, littermate_pattern='_WT')
	assert_equals(sorted(wt_expected), sorted(wt_result))
	assert_equals(sorted(mut_expected), sorted(mut_result))
