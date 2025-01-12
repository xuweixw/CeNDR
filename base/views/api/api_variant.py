#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Author: Daniel E. Cook
"""
import re
import pickle
from cyvcf2 import VCF
from flask import request, Response
from tempfile import NamedTemporaryFile
from subprocess import Popen, PIPE
from collections import OrderedDict
from base.utils.decorators import jsonify_request
from base.config import config
from collections import Counter
from logzero import logger

from flask import Blueprint

api_variant_bp = Blueprint('api_variant',
                           __name__,
                           template_folder='api')

# Load the gene dictionary on server start
gene_id_dict = pickle.load(open("base/static/data/gene_dict.pkl", 'rb'))

ANN_header = ["allele",
              "effect",
              "impact",
              "gene_name",
              "gene_id",
              "feature_type",
              "feature_id",
              "transcript_biotype",
              "exon_intron_rank",
              "nt_change",
              "aa_change",
              "cDNA_position/cDNA_len",
              "protein_position",
              "distance_to_feature",
              "error"]


def get_vcf(release=config["DATASET_RELEASE"], filter_type="hard"):
    return "http://storage.googleapis.com/elegansvariation.org/releases/{release}/variation/WI.{release}.{filter_type}-filter.isotype.vcf.gz".format(release=release, filter_type=filter_type)


gt_set_keys = ["SAMPLE", "GT", "FT", "TGT"]

ann_cols = ['allele',
            'effect',
            'impact',
            'gene_name',
            'gene_id',
            'feature_type',
            'feature_id',
            'transcript_biotype',
            'exon_intron_rank',
            'nt_change',
            'aa_change',
            'protein_position',
            'distance_to_feature']


def truncate(s, max_len = 20):
    if len(s) >= max_len:
        return s[:max_len] + " …"
    return s

@api_variant_bp.route('/api/variant', methods=["GET", "POST"])
@jsonify_request
def variant_query(query=None, samples=None, list_all_strains=False, release=config["DATASET_RELEASE"]):
    """
    Used to query a VCF and return results in a dictionary.
    """
    if query:
        # Query in Python
        chrom, start, end = re.split(':|-', query)
        query = {'chrom': chrom,
                 'start': int(start),
                 'end': int(end),
                 'release': release,
                 'variant_impact': ['ALL'],
                 'sample_list': samples,
                 'output': "",
                 'list-all-strains': list_all_strains,
                 'variant-annotation': 'bcsq'}
    else:
        # Query from Browser
        query = request.args
        query = {'chrom': query['chrom'],
                 'start': int(query['start']),
                 'end': int(query['end']),
                 'release': query['release'],
                 'variant_impact': query['variant_impact'].split("_"),
                 'sample_list': query['sample_tracks'].split("_"),
                 'output': query['output'],
                 'list-all-strains': list_all_strains or query['list-all-strains'] == 'true',
                 'variant-annotation': query.get('variant-annotation', 'bcsq')}

    logger.debug(query)

    # Two types of variant queries can occur.
    # (1) Variant query of the soft-filter VCF - querying the SNPeff annotations
    # (2) Variant query of the hard-filter VCF - querying the BCSQ annotations

    # Determine which VCF is going to be queried
    vcf = get_vcf(release=query['release'], filter_type='hard')
    available_samples = VCF(vcf).samples

    # Limit queries to 100kb
    if query['end'] - query['start'] > 1e5:
        query['end'] = query['start'] + 1e5

    samples = query['sample_list']
    if query['list-all-strains']:
        samples = "ALL"
    elif not samples:
        samples = "N2" if "N2" in available_samples else available_samples[0]
    else:
        samples = ','.join([x for x in samples if x in available_samples])

    chrom = query['chrom']
    start = query['start']
    end = query['end']

    if start >= end:
        return "Invalid start and end region values", 400

    region = "{chrom}:{start}-{end}".format(**locals())
    comm = ["bcftools", "view", vcf, region]
    logger.debug(comm)

    # Query samples
    if samples != 'ALL':
        comm = comm[0:2] + ['--force-samples', '--samples', samples] + comm[2:]
    out, err = Popen(comm, stdout=PIPE, stderr=PIPE).communicate()
    if not out and err:
        logger.error(err)
        return err, 400
    tfile = NamedTemporaryFile(mode='w+b')
    with tfile as f:
        f.write(out)
        f.flush()
        output_data = []

        v = VCF(f.name, gts012=True)

        if samples and samples != "ALL":
            samples = samples.split(",")
            incorrect_samples = [x for x in samples if x not in v.samples]
            if incorrect_samples:
                return "Incorrectly specified sample(s): " + ','.join(incorrect_samples), 400

        for i, record in enumerate(v):
            INFO = dict(record.INFO)

            ANN = []
            if "ANN" in INFO.keys():
                ANN_set = INFO['ANN'].split(",")
                for ANN_rec in ANN_set:
                    annotation_dict = dict(zip(ANN_header, ANN_rec.split("|")))
                    # Fill in locus id for gene name
                    annotation_dict["gene_name"] = gene_id_dict.get(annotation_dict["gene_id"])
                    ANN.append(annotation_dict)
                del INFO['ANN']

            # Extract FT (genotype filter status)
            try:
                FT = record.format("FT")
                if FT is not None:
                    FT = FT.tolist()
                else:
                    FT = ["PASS" for x in v.samples]
            except KeyError:
                FT = ["PASS"] * len(v.samples)

            gt_set = zip(v.samples, record.gt_types.tolist(), FT, record.gt_bases.tolist())
            gt_set = [dict(zip(gt_set_keys, x)) for x in gt_set]
            ANN = [x for x in ANN if x['impact'] in query['variant_impact'] or 'ALL' in query['variant_impact']]
            if type(INFO['AF']) == tuple:
                AF = INFO['AF'][0]
            else:
                AF = INFO['AF']
            rec_out = {
                "CHROM": record.CHROM,
                "POS": record.POS,
                "REF": truncate(record.REF),
                "ALT": [truncate(x) for x in record.ALT],
                "FILTER": record.FILTER or 'PASS',  # record.FILTER is 'None' for PASS
                "GT": gt_set,
                "AF": '{:0.3f}'.format(AF),
                "ANN": ANN,
                "GT_Summary": Counter(record.gt_types.tolist())
            }

            if len(rec_out['ANN']) > 0 or 'ALL' in query['variant_impact']:
                output_data.append(rec_out)
            if i == 1000 and query['output'] != "tsv":
                return output_data
        if query['output'] == 'tsv':
            filename = f"{query['chrom']}-{query['start']}-{query['end']}.tsv"
            build_output = OrderedDict()
            output = []
            header = False
            for rec in output_data:
                for k in ['CHROM', 'POS', "REF", "ALT", "FILTER", "phastcons", "phylop", "AF"]:
                    if k == 'ALT':
                        build_output[k] = ','.join(rec[k])
                    else:
                        build_output[k] = rec.get(k) or "NA"
                if rec['ANN']:
                    for ann in rec['ANN']:
                        for k in ann_cols:
                            build_output[k] = ann.get(k) or "NA"
                else:
                    for k in ann_cols:
                        build_output[k] = ""

                for gt in rec['GT']:
                    sample = gt['SAMPLE']
                    build_output[sample + '_GT'] = gt['GT']
                    build_output[sample + '_FT'] = gt['FT']
                if header is False:
                    output.append('\t'.join(build_output.keys()))
                    header = True
                output.append('\t'.join(map(str, build_output.values())))
            return Response('\n'.join(output), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=%s" % filename})
        return output_data
