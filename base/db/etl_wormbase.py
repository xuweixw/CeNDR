# -*- coding: utf-8 -*-
"""

Functions in this script are used to load
information from wormbase into the 
CeNDR database

Author: Daniel E. Cook (danielecook@gmail.com)
"""

import csv
import gzip
from gtfparse import read_gtf_as_dataframe
from urllib.request import urlretrieve, urlopen
from tempfile import NamedTemporaryFile
from base.constants import WORMBASE_BUILD, CHROM_NUMERIC
from base.utils.genetic_utils import arm_or_center
from base.models2 import wormbase_gene_summary_m

# Gene GTF defines biotype, start, stop, etc.
# The GTF does not include locus names (pot-2, etc), so we download them in the get_gene_ids function.
GENE_GTF_URL = f"ftp://ftp.wormbase.org/pub/wormbase/releases/{WORMBASE_BUILD}/species/c_elegans/PRJNA13758/c_elegans.PRJNA13758.{WORMBASE_BUILD}.canonical_geneset.gtf.gz"


# GENE GFF_URL
GENE_GFF_URL = f"ftp://ftp.wormbase.org/pub/wormbase/releases/{WORMBASE_BUILD}/species/c_elegans/PRJNA13758/c_elegans.PRJNA13758.{WORMBASE_BUILD}.annotations.gff3.gz"

# Maps wormbase ID to locus name
GENE_IDS_URL = f"ftp://ftp.wormbase.org/pub/wormbase/species/c_elegans/annotation/geneIDs/c_elegans.PRJNA13758.current.geneIDs.txt.gz"

# Lists C. elegans orthologs
ORTHOLOG_URL = f"ftp://ftp.wormbase.org/pub/wormbase/species/c_elegans/PRJNA13758/annotation/orthologs/c_elegans.PRJNA13758.current_development.orthologs.txt"

def get_gene_ids():
    """
        Retrieve mapping between wormbase IDs (WB000...) to locus names.
        Uses the latest IDs by default.
        Gene locus names (e.g. pot-2)
    """
    gene_locus_names_file = NamedTemporaryFile('wb', suffix=".gz")
    out, err = urlretrieve(GENE_IDS_URL, gene_locus_names_file.name)
    return dict([x.split(",")[1:3] for x in gzip.open(out, 'r').read().decode('utf-8').splitlines()])




def fetch_gene_gtf():
    """
        LOADS wormbase_gene
        This function fetches and parses the canonical geneset GTF
        and yields a dictionary for each row.
    """
    gene_gtf_file = NamedTemporaryFile('wb', suffix=".gz")
    out, err = urlretrieve(GENE_GTF_URL, gene_gtf_file.name)
    gene_gtf = read_gtf_as_dataframe(gene_gtf_file.name)

    gene_ids = get_gene_ids()
    # Add locus column
    # Rename seqname to chrom
    gene_gtf = gene_gtf.rename({'seqname':'chrom'}, axis='columns')
    gene_gtf = gene_gtf.assign(locus=[gene_ids.get(x) for x in gene_gtf.gene_id])
    gene_gtf = gene_gtf.assign(chrom_num=[CHROM_NUMERIC[x] for x in gene_gtf.chrom])
    gene_gtf = gene_gtf.assign(pos = (((gene_gtf.end - gene_gtf.start)/2) + gene_gtf.start).map(int))
    gene_gtf['arm_or_center'] = gene_gtf.apply(lambda row: arm_or_center(row['chrom'], row['pos']), axis=1)
    for row in gene_gtf.to_dict('records'):
        yield row


def fetch_gene_gff_summary():
    """
        LOADS wormbase_gene_summary
        This function fetches data for wormbase_gene_summary;
        It's a condensed version of the wormbase_gene_table
        constructed for convenience.
    """

    gene_gff_file = NamedTemporaryFile('wb', suffix=".gz")
    out, err = urlretrieve(GENE_GFF_URL, gene_gff_file.name)

    WB_GENE_FIELDSET = ['ID', 'biotype', 'sequence_name', 'chrom', 'start', 'end', 'locus']

    with gzip.open(out) as f:
        for line in f:
            line = line.decode('utf-8')
            if 'WormBase' in line and 'gene' in line:
                line = line.strip().split("\t")
                gene = dict([x.split("=") for x in line[8].split(";")])
                gene.update(zip(["chrom", "start", "end"],
                                [line[0], line[3], line[4]]))
                gene = {k.lower(): v for k, v in gene.items() if k in WB_GENE_FIELDSET}
                
                # Change add chrom_num
                gene['chrom_num'] = CHROM_NUMERIC[gene['chrom']]
                gene['start'] = int(gene['start'])
                gene['end'] = int(gene['end'])
                # Annotate gene with arm/center
                gene_pos = int(((gene['end'] - gene['start'])/2) + gene['start'])
                gene['arm_or_center'] = arm_or_center(gene['chrom'], gene_pos)
                if 'id' in gene.keys():
                    gene_id_type, gene_id = gene['id'].split(":")
                    gene['gene_id_type'], gene['gene_id'] = gene['id'].split(":")

                    del gene['id']
                    yield gene


def fetch_orthologs():
    """
        LOADS (part of) homologs
        Fetches orthologs from wormbase; Stored in the homolog table.
    """
    orthologs_file = NamedTemporaryFile('wb', suffix=".txt")
    out, err = urlretrieve(ORTHOLOG_URL , orthologs_file.name)
    csv_out = list(csv.reader(open(out, 'r'), delimiter='\t'))

    for line in csv_out:
        size_of_line = len(line)
        if size_of_line < 2:
            continue
        elif size_of_line == 2:
            wb_id, locus_name = line
        else:
            yield {'gene_id': wb_id,
                   'gene_name': locus_name,
                   'homolog_species': line[0],
                   'homolog_taxon_id': None,
                   'homolog_gene': line[2],
                   'homolog_source': line[3],
                   'is_ortholog': line[0] == 'Caenorhabditis elegans'}