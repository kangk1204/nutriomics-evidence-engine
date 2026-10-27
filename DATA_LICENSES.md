# Software and data licenses

## Project software

The original code and documentation in this repository are distributed under the [MIT License](LICENSE). Dependencies installed through Python, R or Bioconductor retain their own licenses.

## Research data

The software license applies to this project's implementation. External datasets, annotations, publications and pretrained model weights retain the terms set by their providers. Cite the original study and accession when using a research dataset. Input hashes, analysis settings and source identifiers accompany the results in `docs/`.

| Resource | Use in this project | Source and terms |
|---|---|---|
| CTD | Chemical, gene and disease relationships; source IDs and aggregate counts | [CTD](https://ctdbase.org/) provides data for noncommercial research; commercial use requires a separate license. See the [2025 database paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC11701581/). Bulk CTD files and generated research databases are obtained separately. |
| FooDB | Food compound mapping and structure normalization | [FooDB terms](https://foodb.ca/compliance): CC BY-NC 4.0. The historical snapshot and processing steps are described in the [source record](docs/food_compound_extension_20261003_v1/SOURCE_AUDIT.md). Source CSV files are obtained separately. |
| DrugProt | Chemical-protein relation evaluation | Obtain the corpus from its [official record](https://doi.org/10.5281/zenodo.5042151) and retain the provider's attribution and terms. The [official evaluation library](https://github.com/tonifuc3m/drugprot-evaluation-library) is MIT-licensed, copyright 2021 Antonio Miranda-Escalada. It is downloaded separately; its pinned commit and checksums are recorded in [evaluation provenance](docs/drugprot_official_evaluator.json). |
| BioRED and BC2GM | Biomedical entity and relation benchmarks | Obtain the corpora from their official distributions via [BioRED](https://ftp.ncbi.nlm.nih.gov/pub/lu/BioRED/) and [BLURB](https://microsoft.github.io/BLURB/tasks.html). Article text and corpus annotations retain their original terms. |
| Qwen2.5-7B-Instruct | Language model relation extraction | [Model card](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct), Apache 2.0. Weights are downloaded separately. |
| BiomedBERT | Biomedical language representation | [Model card](https://huggingface.co/microsoft/BiomedNLP-BiomedBERT-base-uncased-abstract-fulltext), MIT. Weights are downloaded separately. |
| PubMed and PMC | Literature retrieval and source links | [NCBI policies](https://www.ncbi.nlm.nih.gov/home/about/policies/) and the license of each article apply to retrieved text. The repository provides source identifiers, extraction code and evaluation records. |

## Reused project code

`integrations/literature_service/` contains the author's existing literature service. Its file selection and original checksums are recorded in the [source manifest](docs/literature_service_source_manifest.json). Runtime databases, article collections, account files and model caches are stored separately.
