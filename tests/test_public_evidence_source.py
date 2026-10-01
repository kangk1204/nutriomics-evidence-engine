import importlib.util
from pathlib import Path
import pytest


script = Path(__file__).resolve().parents[1]/"scripts"/"fetch_public_evidence.py"
spec = importlib.util.spec_from_file_location("public_evidence_fetch",script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_book_article_abstract_and_original_ids():
    xml = b'''<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>28230950</PMID>
    <ArticleIdList><ArticleId IdType="bookaccession">NBK401702</ArticleId><ArticleId IdType="doi">10.1/book</ArticleId></ArticleIdList>
    <Book><BookTitle>Parent book</BookTitle><PubDate><Year>2021</Year></PubDate></Book>
    <ArticleTitle>Chapter <i>title</i></ArticleTitle><PublicationType>Review</PublicationType>
    <Abstract><AbstractText Label="BACKGROUND">Blood <b>pressure</b>.</AbstractText></Abstract>
    </BookDocument></PubmedBookArticle></PubmedArticleSet>'''
    record = module.parse_pubmed(xml)[0]
    assert record['record_type']=='PubmedBookArticle'
    assert record['pmid']=='28230950' and record['book_accession']=='NBK401702'
    assert record['title']=='Chapter title' and record['abstract']=='BACKGROUND: Blood pressure.'
    assert record['book_title']=='Parent book' and record['publication_types']==['Review']


def test_missing_or_withdrawn_pmids_remain_auditable_without_invented_records():
    records = module.parse_pubmed(b'<PubmedArticleSet><DeleteCitation><PMID>12</PMID></DeleteCitation></PubmedArticleSet>')
    assert records==[]
    ledger = module.completeness_ledger(['12'],records)
    assert ledger['missing_pmids']==['12'] and ledger['returned_records']==0 and not ledger['complete']
    with pytest.raises(ValueError,match='Unrequested PMID'):
        module.completeness_ledger(['12'],[{'pmid':'13'}])


def test_malformed_source_record_rejected():
    with pytest.raises(ValueError,match='citation/body'):
        module.parse_pubmed(b'<PubmedArticleSet><PubmedBookArticle/></PubmedArticleSet>')
