# 원출처·권한·측정 범위

이 문서는 각 출처에서 실제 확인한 범위를 기록한다. 원문 전체, 원표, 그림, 개인 데이터는 이 패킷에 포함하지 않는다. 공개 승인된 것은 새로 작성한 사실 메타데이터와 문헌 링크이다. 확인하지 못한 DOI, 분석 n, 효과량, CI, 권한은 추정하지 않았다.

| ID | 원출처 | 실제 확인 범위 | 원출처 이용 조건 확인 |
|---|---|---|---|
| S01 | [Broccoli upper-airway RNA intervention](https://pubmed.ncbi.nlm.nih.gov/19028145/); 10.1016/j.clim.2008.10.007; PMID 19028145 | Primary abstract read; original methods/n and numerical folds not extracted | not_verified |
| S02 | [Broccoli ozone-challenge negative POC](https://link.springer.com/article/10.1186/s12931-016-0406-8); 10.1186/s12931-016-0406-8; PMID 27450419 | Primary full methods/results/discussion and rights read | CC-BY-4.0 |
| S03 | [Orange/hesperidin leukocyte transcriptomics](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0026669); 10.1371/journal.pone.0026669; PMID 22110589 | Primary full methods/results/discussion read; selected targets, not all supplementary rows | CC-BY; version not resolved |
| S04 | [Orange/hesperidin vascular crossover trial](https://pubmed.ncbi.nlm.nih.gov/21068346/); 10.3945/ajcn.110.004945; PMID 21068346 | Primary abstract read; effect size/CI unavailable | not_verified |
| S05 | [Olive-phenol postprandial PBMC transcriptomics](https://link.springer.com/article/10.1186/1471-2164-11-253); 10.1186/1471-2164-11-253; PMID 미확인/해당 없음 | Primary full methods/results/discussion and rights read; exact per-gene supplement not imported | CC-BY-2.0 |
| S06 | [Cocoa global methylation and ex-vivo RNA](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0065744); 10.1371/journal.pone.0065744; PMID 미확인/해당 없음 | Primary methods/results read; two earlier-trial run-in cohorts distinguished | CC-BY; version not resolved |
| S07 | [Flaxseed pre-surgery tumor biomarker trial](https://pubmed.ncbi.nlm.nih.gov/15897583/); 10.1158/1078-0432.CCR-04-2326; PMID 15897583 | Primary abstract and indexed primary publisher methods; RNA not measured | not_verified |
| S08 | [B-PROOF methylation substudy](https://link.springer.com/article/10.1186/s13148-015-0154-5); 10.1186/s13148-015-0154-5; PMID 26568774 | Primary methods/results read; selected exact CpGs and DMP-vs-DMR distinction | not_verified |
| S09 | [B-PROOF fracture endpoint](https://pubmed.ncbi.nlm.nih.gov/25411293/); DOI 미확인; PMID 25411293 | Primary indexed abstract n/dose/ITT HR and conclusion; DOI not currently extracted | not_verified |
| S10 | [PREDIMED-Navarra methylation substudy](https://pubmed.ncbi.nlm.nih.gov/29295516/); 10.3390/nu10010015; PMID 29295516 | Primary abstract/figure legends plus indexed primary full-results direction; full supplements not imported | not_verified |
| S11 | [Corrected/re-published PREDIMED health trial](https://pubmed.ncbi.nlm.nih.gov/29897866/); 10.1056/NEJMoa1800389; PMID 29897866 | Primary abstract read including randomization departures and revised effect estimates | not_verified |
| S12 | [USDA Flavonoid Release3.3 white-tea composition](https://www.ars.usda.gov/ARSUserFiles/80400535/Data/Flav/Flav3.3.pdf); DOI 미확인; PMID 미확인/해당 없음 | Official documentation and native99582 row parsed; no local full-dataset import or source-byte rehash | USDA federal source; artifact-specific upstream raw-data rights not assessed |
| S13 | [EGCG promoter demethylation in cancer cells](https://pubmed.ncbi.nlm.nih.gov/14633667/); DOI 미확인; PMID 14633667 | Primary abstract read; no DOI reported in retrieved record; n/CI unavailable | not_verified |
| S14 | [EGCG increases astrocyte COX2/PGE2](https://pubmed.ncbi.nlm.nih.gov/15210717/); 10.1074/jbc.M402085200; PMID 15210717 | Primary abstract read; original n/dose/time/quantitative effects unavailable | not_verified |

S07은 PubMed 초록과 검색에 노출된 원 출판사 방법 설명을 확인했으며, 원 출판사 전체 본문 접근은 실패했다. S09는 검색에 노출된 원 초록을 확인했다. S10은 원 초록·그림 설명과 검색에 노출된 원 결과의 방향을 확인했으며 전체 보충자료는 가져오지 않았다. 접근 실패를 우회하지 않았다. S12는 공식 PDF의 설명과 99582 행을 도구가 추출한 텍스트로 확인했으며 픽셀 이미지 확인, 전체 파일 다운로드, 원 파일 바이트 해시를 수행하지 않았다.

현재 패널은 Library 문서 `libfile_9da423931d988191b9c84fe7c9e71f14`의 인쇄된 50 CpG이며, 원래 패널 CpG/유전자 표는 50–51쪽에 있다. 39행에 원래 유전자 주석이 있고, 중복 제외 22개 원래 유전자 라벨과 미주석 11행을 보존했다. Body, TSS200/1500, UTR 등 위치 라벨은 유전자로 처리하지 않았다. hg19/GPL13534 원래 라벨을 보존했으며 새 HGNC/Ensembl 정규화 영수증은 없다.

POC의 정확 CpG 4개(`cg06191076`, `cg19380919`, `cg01081346`, `cg17071192`)는 이 50개 패널과 정확 일치하지 않는다. 이 결과는 선택된 4좌위에 한정된다. 전체 EWAS, P03의 전체 차등발현 목록, 4,630개 음식·성분 구조 조인이 검증된 것은 아니다. 모든 사례의 canonical gene overlap은 `null`이다.

P04의 개별 hydroxytyrosol 단위가 총 페놀 함량과 조화되지 않으므로 개별 용량은 `null`이다. P02의 유전자별 분석 n과 P06의 IHC 표지별 분석 n도 전체 참여자 수로 채우지 않았다. P09·P10의 백차 성분 행은 같은 조성 측정이며 독립된 두 번의 측정 또는 반복 재현이 아니다.
