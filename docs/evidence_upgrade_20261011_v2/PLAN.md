# 근거 보강 계획: 선행연구·DB 비교 후 구현/평가

기준 문서 패키지: `7b41dc14bacbf02a8c6fe52810c6a7da10209925`. Mac 연결과 로컬 실행 도구는 현재 없다. 계획을 먼저 저장하고, 그 다음 API와 독립된 문서용 감사 코드를 구현한다. 전체4,630개 성분 범위는 유지한다. 작은 사례/합성 fixture는 단계적 코드 QA이며 전체 연구 범위를 대체하지 않는다.

## 조사 결과와 비교 기준

[FoodMine2020](https://www.nature.com/articles/s41598-020-73105-0)는 식품 화학 문헌·정량 정보 추출 선행연구다. [FoodAtlas2024](https://doi.org/10.1016/j.compbiomed.2024.109072)와 [FoodAtlas2026](https://www.nature.com/articles/s41538-025-00680-9)은 매우 유사한 graph 선행연구다. 부모 연구자가 확인한 후자 정보에 따르면 foodchemical 정량·CTD·ChEMBL·provenance를 연결하며, F1.67은 그 논문의 추출 평가이고 위험 감소는 시뮬레이션이다. 본 작업에서 그 성능을 재현하지 않았다. API키나 제한 데이터를 새로 취득하지 않는다. 단순 graph 통합이나 음식→질환 연결을 신규성·임상성과로 주장하지 않는다.

비교 기준은 개체/관계 분모, 정확한 화학·유전자 식별자, native form/조리/부위/단위, 연구 맥락, full source/statistical provenance, 출처 권리, 독립 참가자·assay·문헌 집단, 실제 독립 평가다. 가까운 유전자나 공유 경로는 인과·결합으로 승격하지 않는다.

| 자료 | 활용 | 한계/검증 조건 |
|---|---|---|
| FDC | 음식·영양소 조성; preparation/basis | Foundation 분석·Branded 라벨·FNDDS 편집·SR Legacy 유래 구분; nutrient ID≠단일 구조 |
| HGNC | stable gene ID·별칭 | native 심볼을 보존하고 출처 해시가 있는 일대일 매핑만 허용; 실제22개 매핑 미회수 |
| ChEBI·PubChem | 분자 정체성·형태 | full key만으로 원 측정 analyte·입체·염을 확정하지 않음; 기여원 조건 분리 |
| Reactome | 종별 반응·경로 | pathway membership≠직접결합·방향·임상 효과 |
| 역사적 FooDB | 동결4,630구조·정량/정성 조성 | 원 형태·종/부위·측정 대입/불명확성 보존; 현재2026자료라고 하지 않음 |
| CTD | 조건부 영향·질환 출처 | 중첩 반응·공동처치·종/조직·source PMID 보존; tox/cell 영향≠음식 효능 |
| BindingDB·ChEMBL | assay endpoint | Kd/Ki/IC50/EC50 분리; 반복 assay/문헌을 독립 재현으로 세지 않음 |
| EWAS Catalog | 정확50CpG 외부 연관 | 이번 home timeout/download503; 미조회/실패/nohit 구분; 정량 성능 미평가 |
| Exposome Explorer | 섭취→생체노출 bridge | 개별 기록·재배포조건 미확인; 농도·시간·조직 일치 필요 |

현재 확인한 라이선스는 [FDC dataCC0](https://fdc.nal.usda.gov/api-guide/), [HGNC dataCC0](https://www.genenames.org/about/license/), [ChEBI CC-BY4+EBI조건](https://www.ebi.ac.uk/chebi/about), [Reactome dataCC0/그림CC-BY4/코드별조건](https://reactome.org/license)이다. FooDB의 기존 receipt는 CC-BY-NC4를 기록하지만 이번 upstream403으로 원문을 재확인하지 못했다. CTD·ChEMBL·PubChem 기여 annotation·EWAS·Exposome은 해당 artifact/목적의 조건을 확인하기 전 dataset export 진단을 차단한다. 실제 공개·권한 변경·dataset export는 수행하지 않는다.

기존 연구 비교는 actual adipocyte McAllan, 혈액 B-PROOF, PREDIMED36명, folate/B12 EWAS5,841명, source-linked Wilson358명과 clock endpoint CALERIE/DO-HEALTH를 포함한다. [PREDIMED의 두 CpG](https://pubmed.ncbi.nlm.nih.gov/29295516/)는 현재50개에 없다. [Wilson 연구](https://www.ars.usda.gov/research/publications/publication/?seqNo115=410641)는 식품 조성 추정과 측정 건강지표의 관찰 연관이며 개인 임상 crosswalk나 현재 CpG 효과를 제공하지 않는다. clock 변화는 현재50CpG·수명·건강효과 증거로 이전하지 않는다. 자세한 access scope는 plan.json에 기록했다.

## 구현 순서와 작업 종료 기준

| 작업 | 종료 기준 | 현재 실행 범위 |
|---|---|---|
| W1 snapshot/출처/분모/권리 | SHA·release·접근 실패·권리 적용 범위 명시 | 조사·계획 산출 |
| W2 50개 위치/주석/QC | 50개 전부 회계; native22심볼 요청; 미조회는 negative가 아님 | 기존 표와 missing/probe/EWAS 상태 |
| W3 exact ID join | 출처가 검증된 일대일 매핑만 조인; ambiguity/name-only fail | 현재 제공된6경로/50CpG subset + fixture |
| W4 맥락·독립성·정량 | 공동처치/중첩/종조직/연구집단/단위/검출한계 보존 | 문서용 감사지표 |
| W5 전달/권리 | licence 미확인 dataset export readiness=false | 진단만; 실제 export 없음 |
| W6 구현 검사/실제 subset 실행 | 정해진 boundary fixture 통과, source-input receipt 유지 | V8 실행; 합성 QA와 실제 subset 결과 분리 |
| W7 전체4,630/원보충표 | sameMac·owner·원본 테이블·해시·권리 확인 후 완전 대조 | 연결/원자료 부재로 blocked |
| W8 보고서/API/독립 과학평가 | 소유자 적용/검사 receipt, 독립 real gold/임상자료 | API 소유자 별도; not applied |

기존 `knowledge/services/evidence.py:291`은 dose와duration 존재를 점수에 더하고,296행은 distinct PMID 수를 반복 점수로 사용한다. 이번에는 값을 **용량 반응 실험/독립 재현 검증**으로 재명명하지 않도록 문서 감사 결과에 각각의 미확인 상태를 만든다. 코드를 변경하거나 새로운 과학 qualification 규칙을 배포하지 않는다.

검사는 입체/염/부위/조리, 단위/검출한계, 정성→가짜 정량, 동물/세포→환자, 미확인 권리, 중복 입력 멱등, timeout/nohit/stale, PMID/공유 cohort, 조건부 방향을 다룬다. Precision/recall은 독립적인 실제 정답 자료가 없어 미평가다. 합성 shuffle·mock 입력은 코드 오류 검사이며 생물학적 음성 실험이 아니다.

계획 자체를 구현 완료로 보고하지 않는다. 구현 코드·실행 입력 범위·검사 결과와 blocked 작업을 후속 receipt로 별도 저장한다.
