#!/usr/bin/env python

"""

"""

import os
import sys
from os.path import join, basename, split

# Hack. Relative package imports won't work if this module is run as __main__
sys.path.insert(0, join(os.path.dirname(__file__), '..'))
from lib import addict
import common
import SimpleITK as sitk
from elastix.invert import InvertSingleVol, InvertStats
from statistical_tests import Zmap
from data_getters import DeformationDataGetter, IntensityDataGetter, JacobianDataGetter, GlcmDataGetter
import numpy as np
import gc
from statistical_tests import LinearModelR, LinearModelNumpy
import logging
import shutil
import tsne
from automated_annotation import Annotator
import csv
import pandas as pd
from scipy.stats import zmap
from img_processing import glcm3d
from os.path import isdir
from os import mkdir

STATS_FILE_SUFFIX = '_stats_'
# CALC_VOL_R_FILE = 'rscripts/calc_organ_vols.R'
CLUSTER_PLOT_NAME = 'mutant_zmap_clustering.png'
CLUSTER_PLOT_NAME_ALL = 'all_specimens_zmap_clustering.png'
MINMAX_TSCORE = 50
FDR_CUTOFF = 0.05


class AbstractPhenotypeStatistics(object):
    """
    The base class for the statistics generators
    """
    def __init__(self, out_dir, analysis_prefix, main_config, analysis_config):
        """
        Parameters
        ----------
        out_dir: str
            path to put the output of the statistical analysis
        analysis_prefix: str
            prepend output files with this string
        main_config: dict
            Obtained from the stats config yaml file and some other stuff from run_lama_stats is added
        analysis_config: dict
            The analysis-specifc config from the yaml config file

        """
        self.line_calibrated_p_values = main_config.line_calibrated_p_values
        self.specimen_calibrated_p_values = main_config.specimen_calibrated_p_values
        self.blur_fwhm = main_config.blur_fwhm
        self.root_dir = main_config.root_dir
        self.normalisation_roi = main_config.normalisation_roi
        self.subsampled_mask = None # Not been using that so deprecate it
        self.do_zmap = main_config.n1
        self.label_map = main_config.label_map
        self.label_names = main_config.label_names
        self.project_name = main_config.project_name
        self.out_dir = out_dir
        common.mkdir_if_not_exists(self.out_dir)
        self.mask = main_config.mask_array_flat  # this is a flat binary array
        self.formulas = main_config.formulas
        self.wt_file_list = main_config.wt_file_list
        self.mut_file_list = main_config.mut_file_list
        self.voxel_size = main_config.voxel_size
        self.n1_out_dir = join(self.out_dir, 'n1')
        self.filtered_stats_path = None  # This is set in weird ways
        self.stats_out_dir = None
        self.n1_tester = Zmap
        self.analysis_config = analysis_config

        # Obtained from the data getter
        self.shape = None

        self.n1_stats_output = []  # Paths to the n1 anlaysis output. Used in inverting stats volumes
        self.groups = main_config.groups


    def _set_data(self):
        """
        Using the class-specific data_getter. Read in the data
        """

        vol_order = self.get_volume_order()
        self.dg = self.data_getter(self.wt_file_list, self.mut_file_list, self.mask, vol_order, self.voxel_size,
                                    self.subsampled_mask, None, self.blur_fwhm, self.root_dir)  # None is subsample which is deprecated

    def get_volume_order(self):
        """

        Returns
        -------

        list: order of volumes in groups file
        """
        if self.groups:
            order = []
            with open(self.groups, 'r') as fh:
                first = True
                reader = csv.reader(fh)
                for row in reader:
                    if first:  # Skip header
                        first = False
                        continue
                    else:
                        order.append(row[0])
            return order

    def run(self, stats_object, analysis_prefix):

        self.analysis_prefix = analysis_prefix

        try:
            self._set_data()
        except IOError as e:
            print('error getting data for {}: {}'.format(self.analysis_prefix, e))
            return False
        normalisation_dir = join(self.out_dir, 'normalised_images')
        self.dg.set_normalisation_roi(self.normalisation_roi, normalisation_dir)  # only used for ItensityStats
        self.dg.set_data()

        logging.info('using wt_paths n={}\n--------------\n{}\n\n'.format(
            len(self.dg.wt_paths), '\n'.join([x for x in self.dg.wt_paths])))

        logging.info('using mut_paths n={}\n--------------\n{}\n\n'.format(
            len(self.dg.mut_paths), '\n'.join([x for x in self.dg.mut_paths])))

        self.shape = self.dg.shape
        self.run_linear_model_stats(stats_object)
        gc.collect()

    def run_linear_model_stats(self, stats_object):
        """

        """

        for formula in self.formulas[:1]:  # Just do one formula for now as it may break
            so = stats_object(self.dg.masked_wt_data, self.dg.masked_mut_data, self.shape, self.out_dir)

            logging.info(common.git_log())
            so.set_formula(formula)
            so.set_groups(self.groups)
            so.run()
            qvals = so.line_qvals
            tstats = so.line_tstats
            pvals = so.line_pvals
            unmasked_tstats = self.rebuid_masked_output(tstats, self.mask, self.mask.shape).reshape(self.shape)
            unmasked_qvals = self.rebuid_masked_output(qvals, self.mask, self.mask.shape).reshape(self.shape)
            filtered_tsats = self.write_results(unmasked_qvals, unmasked_tstats, so.STATS_NAME, formula)
            t_threshold_file = join(self.out_dir, 'Qvals-{}.csv'.format(self.type))
            write_threshold_file(unmasked_qvals, unmasked_tstats, t_threshold_file)

            self.log_summary(tstats, pvals, qvals)

            if self.label_map is not None and self.label_names is not None:
                logging.info("Doing auto annotation")
                ann_outpath = join(self.out_dir, 'annotation.csv')
                Annotator(self.label_map, self.label_names, filtered_tsats, ann_outpath)
            else:
                logging.info("Skipping auto annotation as there was either no labelmap or list of label names")

            # Get the specimen calls and write to disk
            for specimen_id, specimen_data in so.specimen_results.items():
                tstats = specimen_data['t']
                qvals = specimen_data['q']
                histogram = specimen_data['histogram']

                try:
                    unmasked_tstats = self.rebuid_masked_output(tstats, self.mask, self.mask.shape).reshape(self.shape)
                except IndexError:
                    pass

                unmasked_qvals = self.rebuid_masked_output(qvals, self.mask, self.mask.shape).reshape(self.shape)

                self.write_results(unmasked_qvals,
                                   unmasked_tstats,
                                   so.STATS_NAME + '_' + specimen_id,
                                   formula,
                                   specimen_id,
                                   histogram)
            del so
            gc.collect()

    def log_summary(self, tstats, pvals, qvals):
        min_t = min(tstats)
        max_t = max(tstats)
        min_p = min(pvals)
        min_q = min(qvals)

        try:
            t_threshold = tstats[(tstats > 0) & (qvals <= 0.05)].min()
        except ValueError:
            try:
                t_threshold = np.abs(tstats[(tstats < 0) & (qvals <= 0.05)].max())
            except ValueError:
                t_threshold = 'No t-statistics below fdr threshold'

        logging.info(
            "\n\nMinimum T score: {}\nMaximum T score: {}\nT threshold at FDR 0.05: {}\nMinimum p-value: {}\nMinimum q-value: {}".format(
                min_t, max_t, t_threshold, min_p, min_q
            ))

    def rebuid_masked_output(self, array, mask, shape):
        """
        The results from the stats are 1D and missing masked regions. Add the result back into a full-sized image.
        Override this method for subsampled analysis e.g. GLCM
        """

        array[array > MINMAX_TSCORE] = MINMAX_TSCORE

        array[array < -MINMAX_TSCORE] = - MINMAX_TSCORE
        full_output = np.zeros(shape)
        full_output[mask != False] = array
        return full_output.reshape(shape)

    def write_results(self, qvals, tstats, stats_name, formula=None, specimen_dir=None, histogram=None):
        """
        Write out q-value-thresholded tstats

        Parameters
        ----------
        qvals: nnumpy.ndarray
        tstats: numpy.ndarray
        stats_name: str
            the analysis name (eg: jacobians)
        formula: str
            The LM formaula
        specimen_dir: str
            if specimen-lelvel analysis folder name to put results in

        Returns
        -------
        numpy.ndarray
            The thresholded tstats
        """
        import seaborn as sns
        import matplotlib.pyplot as plt

        stats_prefix = self.project_name + '_' + self.analysis_prefix
        if formula:
            stats_prefix += '_' + formula

        if specimen_dir:
            stats_outdir = join(self.out_dir, 'specimen_level', stats_name)
        else:
            stats_outdir = join(self.out_dir, stats_name)

        common.mkdir_if_not_exists(stats_outdir)

        outpath = join(stats_outdir,
                       stats_prefix + '_' + stats_name + '_' + formula + '_FDR_' + str(0.5) + '_stats_.nrrd')

        if not specimen_dir:
            #  These instance variables are used elswhere and needs to be set when the line level results are being
            #  written. This needs changing
            self.stats_out_dir = stats_outdir # Why do I set an instance variable here. Don't like
            self.filtered_stats_path = outpath

        if histogram is not None:

            x = np.linspace(0, 1, num=histogram.size)
            sns.barplot(x, histogram)
            plotpath = join(stats_outdir, 'p-value_histogram.png')
            plt.savefig(plotpath)
            plt.close()

        # Write filtered tstats overlay. Done here so we don't have filtered and unfiltered tstats in memory
        # at the same time
        try:
            filtered_tsats = self._result_cutoff_filter(tstats, qvals)
        except ValueError:
            print "Tstats and qvalues are not equal size"
        else:
            common.write_array(filtered_tsats, outpath)
        gc.collect()
        return filtered_tsats


    @staticmethod
    def _result_cutoff_filter(t, q):
        """
        Convert to numpy arrays and set to zero any tscore that has a corresponding pvalue > 0.05

        Parameters
        ----------

        """
        if len(t) != len(q):
            raise ValueError
        else:
            mask = q > FDR_CUTOFF
            t[mask] = 0

        return t

    def invert(self, invert_config_path):
        """
        Invert the stats back onto the rigidly aligned volumes

        Parameters
        ----------
        invert_order: dict
            Contains inversion order information
        """
        # TODO.

        # Invert the n1 stats
        n1_invert_out_dir = join(self.n1_out_dir, 'inverted')
        common.mkdir_if_not_exists(n1_invert_out_dir)
        for stats_vol_path in self.n1_stats_output:
            n1_inverted_out = join(n1_invert_out_dir, basename(stats_vol_path))
            inv = InvertSingleVol(invert_config_path, stats_vol_path, n1_inverted_out)
            inv.run(prefix=self.n1_prefix)

        # Invert the Linear model/ttest stats
        if not self.filtered_stats_path:
            return

        # inverted_stats
        stats_invert_dir = join(self.stats_out_dir, 'inverted')
        common.mkdir_if_not_exists(stats_invert_dir)
        invs = InvertStats(invert_config_path, self.filtered_stats_path, stats_invert_dir)
        invs.run()


class IntensityStats(AbstractPhenotypeStatistics):
    def __init__(self, *args, **kwargs):
        super(IntensityStats, self).__init__(*args, **kwargs)
        self.data_getter = IntensityDataGetter
        self.type = 'intensity'


class GlcmStats(AbstractPhenotypeStatistics):
    def __init__(self, *args, **kwargs):
        super(GlcmStats, self).__init__(*args, **kwargs)
        self.data_getter = GlcmDataGetter
        self.type = 'GLCM'

    def rebuid_masked_output(self, array, mask, shape):
        """

        """
        array[array > MINMAX_TSCORE] = MINMAX_TSCORE
        array[array < -MINMAX_TSCORE] = - MINMAX_TSCORE

        shape = self.dg.shape
        mask = self.mask.reshape(shape)
        output_array = np.zeros(shape, dtype=np.float32)
        common.rebuild_subsamlped_output(array, output_array, glcm3d.CHUNK_SIZE, mask)
        return output_array


class JacobianStats(AbstractPhenotypeStatistics):
    # Not used. Intensity and jacoabian analysis is the same
    def __init__(self, *args, **kwargs):
        super(JacobianStats, self).__init__(*args, **kwargs)
        self.data_getter = JacobianDataGetter
        self.type = 'jacobian'


class DeformationStats(AbstractPhenotypeStatistics):
    def __init__(self, *args, **kwargs):
        super(DeformationStats, self).__init__(*args, **kwargs)
        self.data_getter = DeformationDataGetter
        self.type = 'deformations'


class OrganVolumeStats(AbstractPhenotypeStatistics):
    """
    The volume organ data does not fit with the other classes above which all work at the pixel not label level
    """
    def __init__(self,  *args, **kwargs):
        super(OrganVolumeStats, self).__init__(*args, **kwargs)
        self.type = 'organvolume'

    def invert(self, _):
        """
        Override the parent invert. Organ volume stats works on already inverted volumes

        """
        return

    def run(self, stats_method_object, analysis_prefix):
        """
        Crun normalised organ volumes thorugh the linear model. The stats.yaml config actually provides te iverted labels
        as input. They are not actually used and are jsut there to enable it to work. I will change this shortly (July 2018)

        The data used are the precomputed baselines and wildtype normalised organ volume CSVs (hard coded path here for now)

        Parameters
        ----------
        stats_method_object
        analysis_prefix

        Returns
        -------

        Notes
        -----
        wt_vols_df and mut_vols_df are pd.DataFrames with specimen_ids in columns (minus extension) and organ volumes in rows

        """
        #TODO: 040618 need to read in path to inverted organ volumes

        # create pandas DataFrames where rows=samples, columns=labels/organs
        csv_name = 'organ_volumes_normed_to_mask.csv'
        from os.path import splitext
        mut_ids = [splitext(basename(x))[0] for x in self.mut_file_list]

        try:
            mut_vols_df = pd.read_csv(join(self.root_dir, self.analysis_config['mut_organ_vol_csv']),
                                  index_col=0)
        except IOError as e:
            logging.warn("Cannot find mutant organ volume csv file. Skipping organ volume stats\n{}".format(e))
            return

        try:
            wt_vols_df = pd.read_csv(join(self.root_dir, self.analysis_config['wt_organ_vol_csv']),
                                 index_col=0)
        except IOError as e:
            logging.warn("Cannot find wild type organ volume csv file. Skipping organ volume stats\n{}".format(e))
            return

        # drop all littermate wildtypes (bodge for 100718)
        mut_vols_df = mut_vols_df[~mut_vols_df.index.str.contains('WT|wt')]

        mut_vols_df = mut_vols_df[mut_vols_df.index.isin(mut_ids)] #bacuase some small ones may have been removed

        mut = mut_vols_df
        wt = wt_vols_df

        # Log the organ volumes
        mut = np.log(mut)
        wt = np.log(wt)

        muts_and_wts = pd.concat([mut, wt])

        # If we have a label info file (self.label_names) extract the descriptive names for the labels
        if self.label_names is not None:
            header = []
            to_drop = []
            for i in muts_and_wts:
                if not int(i) in self.label_names.label.values:  # Maybe some gaps in the labelling
                    to_drop.append(i)
                else:
                    header.append(self.label_names[self.label_names.label == int(i)].label_name.values[0])

            # Drop labels that are not present in the label info file
            mut.drop(columns=to_drop, inplace=True)
            wt.drop(columns=to_drop, inplace=True)

        else:  # If no label names file, we just use the organ volume numbers
            header = muts_and_wts.columns

        # Henrik wants the difference between orga and the mean
        label_means = wt.mean(axis=0)

        # Get the line level results
        mut_vals = mut.values
        wt_vals = wt.values
        so = LinearModelR(wt_vals, mut_vals,  self.shape, self.out_dir)

        so.set_formula(self.formulas[0])
        so.set_groups(self.groups)
        so.run()
        line_qvals = so.line_qvals
        pvals = so.line_pvals

        tstats = so.line_tstats # rename is so to line_tstats

        significant = ['yes'if x <= 0.05 else 'no' for x in line_qvals]
        volume_stats_path = join(self.out_dir, 'inverted_organ_volumes_LinearModel_FDR5%.csv')
        columns = ['p', 'q', 't', 'significant']
        stats_df = pd.DataFrame(index=header, columns=columns)
        stats_df['p'] = list(pvals)
        stats_df['q'] = line_qvals
        stats_df['t'] = tstats
        stats_df['significant'] = significant

        # Call significant based on p-thresholds from permutations if available.
        if self.line_calibrated_p_values:
            p_thresh_df = pd.read_csv(self.line_calibrated_p_values, index_col=0)
            stats_df = stats_df.merge(right=p_thresh_df[['p_thresh', 'fdr', 'label_name']], right_on='label_name', left_index=True)
            stats_df['calibrated_significant'] = stats_df['p'] <= stats_df['p_thresh']

        stats_df = stats_df.sort_values('q')
        stats_df.to_csv(volume_stats_path)

        # Now the specimen-level results
        specimen_calls_dir = join(self.out_dir, 'specimen_calls')
        if not isdir(specimen_calls_dir):
            mkdir(specimen_calls_dir)

        for specimen_id, specimen_data in so.specimen_results.items():
            tstats = specimen_data['t']
            qvals = specimen_data['q']
            pvals = specimen_data['p']
            # histogram = specimen_data['histogram']
            significant = ['yes' if x <= 0.05 else 'no' for x in qvals]
            volume_stats_path = join(specimen_calls_dir, '{}_inverted_organ_volumes_LM_FDR5%.csv'.format(specimen_id))
            columns = ['p', 'q', 't', 'significant']
            spec_stats_df = pd.DataFrame(index=header, columns=columns)
            spec_stats_df['p'] = list(pvals)
            spec_stats_df['q'] = qvals
            spec_stats_df['t'] = tstats
            id_ = common.strip_img_extension(specimen_id)
            spec_stats_df['significant'] = significant

            # Call significant based on p-thresholds from permutations if available.
            if self.specimen_calibrated_p_values:
                p_thresh_df = pd.read_csv(self.specimen_calibrated_p_values, index_col=0)
                spec_stats_df = spec_stats_df.merge(right=p_thresh_df[['p_thresh', 'fdr', 'label_name']], right_on='label_name',
                                          left_index=True)
                spec_stats_df['calibrated_significant'] = stats_df['p'] <= stats_df['p_thresh']

            # Add ratio diffs
            spec_mean_diff = mut.loc[id_] / label_means
            spec_stats_df['mean_diff'] = list(spec_mean_diff)

            # Sort
            spec_stats_df = spec_stats_df.sort_values('q')

            spec_stats_df.to_csv(volume_stats_path)


def write_threshold_file(pvals, tvals, outpath):
    """
    Replicate the 'Qvlas-intensities/jacobians.csv' output by the TCP pipeline. Needed for gettting our data up onto
    IMPC pipeline. All we neeed is the first and last column, so just ad 'NA' for all the others

        An eample file looks like this
            "","F-statistic","tvalue-(Intercept)","tvalue-gf$genotypeKO"
            "0.01",NA,6.04551674399839,NA
            "0.05",NA,4.063447298063,NA
            "0.1",30.8843220744942,3.27694469338307,5.55736646933547
            "0.15",20.2650883331287,2.83426768232588,4.50167616928725
            "0.2",15.2004082182636,2.51876041070957,3.89877009045976
    """

    rows = ['"","F-statistic","tvalue-(Intercept)","tvalue-gf$genotypeKO"\n']
    row_template = '"{}", NA, NA, {}\n'
    for pvalue in [0.000001, 0.00001, 0.0001, 0.001, 0.005, 0.01, 0.05, 0.1, 0.15, 0.2]:
        try:
            t_thresh = np.min(tvals[np.where((pvals <= pvalue) & (tvals > 0))])
        except ValueError:  # No minimum availbale
            t_thresh = 'NA'

        row = row_template.format(str(pvalue), str(t_thresh))
        rows.append(row)
    with open(outpath, 'w') as fh:
        for r in rows:
            fh.write(r)


def get_label_vols(label_paths, verbose=False):
    """

    Parameters
    ----------
    label_paths: str
        paths to labelmap volumes

    Returns
    -------
    Dict: {volname:label_num: [num_voxels_1, num_voxels2...]...}
    """

    label_volumes = addict.Dict()
    num_volumes = len(label_paths)

    for i, label_path in enumerate(label_paths):
        if verbose:
            print("{}/{}".format(i + 1, num_volumes))
        # Get the name of the volume
        volname = os.path.split(split(label_path)[0])[1]
        labelmap = sitk.ReadImage(label_path)

        lsf = sitk.LabelStatisticsImageFilter()
        labelmap = sitk.Cast(labelmap, sitk.sitkUInt16)
        lsf.Execute(labelmap, labelmap)
        num_labels = lsf.GetNumberOfLabels()
        for i in range(1, num_labels + 1):
            voxel_count= lsf.GetCount(i)
            label_volumes[volname][i] = voxel_count
    return pd.DataFrame(label_volumes.to_dict())


if __name__ == '__main__':
    # Just dev out the p/t threshold file
    import sys
    pt = sys.argv[1]  # lama npz file containg q and t values
    out = sys.argv[2]

    data = np.load(pt)
    q = data['qvals'][0].astype(np.float16)
    t = data['tvals'][0].astype(np.float16)

    write_threshold_file(q, t, out)








