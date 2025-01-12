import os
import arrow
import pickle

from rich.console import Console
from base import constants
from base.constants import URLS
from base.utils.data_utils import download
from base.utils.gcloud import upload_file
from base.models import (db,
                         Strain,
                         Homologs,
                         Metadata,
                         WormbaseGene,
                         WormbaseGeneSummary)
from base.config import (CENDR_VERSION,
                         APP_CONFIG,
                         DATASET_RELEASE,
                         WORMBASE_VERSION,
                         RELEASES)
# ETL Pipelines - fetch and format data for
# input into the sqlite database
from base.database.etl_homologene import fetch_homologene
from base.database.etl_strains import fetch_andersen_strains
from base.database.etl_wormbase import (fetch_gene_gff_summary,
                                        fetch_gene_gtf,
                                        fetch_orthologs)

console = Console()
DOWNLOAD_PATH = ".download"


def download_fname(download_path: str, download_url: str):
    return os.path.join(download_path,
                        download_url.split("/")[-1])


def initialize_sqlite_database(sel_wormbase_version,
                               strain_only=False):
    """Create a static sqlite database
    Args:
         sel_wormbase_version - e.g. WS245

    Generate an sqlite database
    """
    start = arrow.utcnow()
    console.log("Initializing Database")

    SQLITE_PATH = f"base/cendr.{DATASET_RELEASE}.{sel_wormbase_version}.db"
    SQLITE_BASENAME = os.path.basename(SQLITE_PATH)

    # Download wormbase files
    if strain_only is False:
        if os.path.exists(SQLITE_PATH):
            os.remove(SQLITE_PATH)

        if not os.path.exists(DOWNLOAD_PATH):
            os.makedirs(DOWNLOAD_PATH)

        # Parallel URL download
        console.log("Downloading Wormbase Data")
        download([URLS.GENE_GFF_URL,
                  URLS.GENE_GTF_URL,
                  URLS.GENE_IDS_URL,
                  URLS.HOMOLOGENE_URL,
                  URLS.ORTHOLOG_URL,
                  URLS.TAXON_ID_URL],
                 DOWNLOAD_PATH)

        gff_fname = download_fname(DOWNLOAD_PATH, URLS.GENE_GFF_URL)
        gtf_fname = download_fname(DOWNLOAD_PATH, URLS.GENE_GTF_URL)
        gene_ids_fname = download_fname(DOWNLOAD_PATH, URLS.GENE_IDS_URL)
        homologene_fname = download_fname(DOWNLOAD_PATH, URLS.HOMOLOGENE_URL)
        ortholog_fname = download_fname(DOWNLOAD_PATH, URLS.ORTHOLOG_URL)

    from base.application import create_app
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{SQLITE_BASENAME}"
    app.app_context().push()

    if strain_only is True:
        db.metadata.drop_all(bind=db.engine, checkfirst=True, tables=[Strain.__table__])
        db.metadata.create_all(bind=db.engine, tables=[Strain.__table__])
    else:
        db.create_all(app=app)
    db.session.commit()

    console.log(f"Created {SQLITE_PATH}")

    ################
    # Load Strains #
    ################
    console.log('Loading strains...')
    db.session.bulk_insert_mappings(Strain, fetch_andersen_strains())
    db.session.commit()
    console.log(f"Inserted {Strain.query.count()} strains")

    if strain_only is True:
        console.log('Finished loading strains')
        return

    ################
    # Set metadata #
    ################
    console.log('Inserting metadata')
    metadata = {}
    metadata.update(vars(constants))
    metadata.update({"CENDR_VERSION": CENDR_VERSION,
                     "APP_CONFIG": APP_CONFIG,
                     "DATASET_RELEASE": DATASET_RELEASE,
                     "WORMBASE_VERSION": sel_wormbase_version,
                     "RELEASES": RELEASES,
                     "DATE": arrow.utcnow()})
    for k, v in metadata.items():
        if not k.startswith("_"):
            # For nested constants:
            if type(v) == type:
                for name in [x for x in dir(v) if not x.startswith("_")]:
                    key_val = Metadata(key="{}/{}".format(k, name),
                                       value=getattr(v, name))
                    db.session.add(key_val)
            else:
                key_val = Metadata(key=k, value=str(v))
                db.session.add(key_val)

    db.session.commit()

    ##############
    # Load Genes #
    ##############
    console.log('Loading summary gene table')
    genes = fetch_gene_gff_summary(gff_fname)
    db.session.bulk_insert_mappings(WormbaseGeneSummary, genes)
    db.session.commit()

    console.log('Loading gene table')
    db.session.bulk_insert_mappings(WormbaseGene, fetch_gene_gtf(gtf_fname, gene_ids_fname))
    gene_summary = db.session.query(WormbaseGene.feature,
                                    db.func.count(WormbaseGene.feature)) \
                             .group_by(WormbaseGene.feature) \
                             .all()
    gene_summary = '\n'.join([f"{k}: {v}" for k, v in gene_summary])
    console.log(f"============\nGene Summary\n------------\n{gene_summary}\n============")

    ###############################
    # Load homologs and orthologs #
    ###############################
    console.log('Loading homologs from homologene')
    db.session.bulk_insert_mappings(Homologs, fetch_homologene(homologene_fname))
    db.session.commit()

    console.log('Loading orthologs from WormBase')
    db.session.bulk_insert_mappings(Homologs, fetch_orthologs(ortholog_fname))
    db.session.commit()

    #############
    # Upload DB #
    #############

    # Upload the file using todays date for archiving purposes
    console.log(f"Uploading Database ({SQLITE_BASENAME})")
    upload_file(f"db/{SQLITE_BASENAME}", SQLITE_PATH)

    diff = int((arrow.utcnow() - start).total_seconds())
    console.log(f"{diff} seconds")

    # =========================== #
    #   Generate gene id dict     #
    # =========================== #
    # Create a gene dictionary to match wormbase IDs to either the locus name
    # or a sequence id
    gene_dict = {x.gene_id: x.locus or x.sequence_name for x in WormbaseGeneSummary.query.all()}
    pickle.dump(gene_dict, open("base/static/data/gene_dict.pkl", 'wb'))


def download_sqlite_database():
    SQLITE_PATH = f"base/cendr.{DATASET_RELEASE}.{WORMBASE_VERSION}.db"
    SQLITE_BASENAME = os.path.basename(SQLITE_PATH)
    download([f"https://storage.googleapis.com/elegansvariation.org/db/{SQLITE_BASENAME}"], "base")
