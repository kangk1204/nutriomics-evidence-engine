# 음식–성분–발현/메틸화–건강 영향 POC 10건

문헌 및 공식 조성 데이터에 근거한 10건을 정리했다. 음식·성분·분자 측정·건강 관찰을 보여 주는 POC를 구성할 근거가 충분한 2건, 부분 근거 5건, 특정 연결을 기각하는 대조 3건이다. **완전한 인과사슬 또는 임상 검증 완료 사례는 0건이다.** 충분한 2건도 유전자 매개효과를 입증하거나 현재 비만 패널을 교정하지 않는다.

| POC | 연결과 실제 관찰 | 판정 | 핵심 한계 / 원출처 |
|---|---|---|---|
| P01 | 브로콜리 새싹 균질액 → SFN → 비강 GSTM1/GSTP1/NQO1/HO-1 RNA 증가 | 부분 | 기도 질환 결과 미측정; 원 연구 n·기간 미확인. [S01](https://pubmed.ncbi.nlm.nih.gov/19028145/) |
| P02 | 다른 새싹 균질액 → 혈중 SFN 증가 → 방어 유전자·오존 후 객담 염증 보호 효과 없음 | 기각 대조 | 해당 3일 교차 연구의 음성 결과; 모든 조리법/환자로 일반화하지 않음. [S02](https://link.springer.com/article/10.1186/s12931-016-0406-8) |
| P03 | 농축액 유래 오렌지주스/hesperidin → 백혈구 CCL26/CX3CR1/CXCL17 RNA 감소·NFKBIB 증가; 혈관 지표 관찰 | POC 근거 충분 | RNA 10명 부분연구; 공복 혈관 반응은 유의하지 않음; 유전자 매개효과 없음. [S03](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0026669), [S04](https://pubmed.ncbi.nlm.nih.gov/21068346/) |
| P04 | 페놀 풍부 버진 올리브유 → PBMC PTGS2/IL1B/IL6 등 RNA 감소 | 부분 | 혼합물 개입; 개별 hydroxytyrosol 용량 충돌; 대사 지표는 차이 없음. [S05](https://link.springer.com/article/10.1186/1471-2164-11-253) |
| P05 | 코코아 크림 → 전역 DNAm 차이; 별도 6명 공여자 세포에서 DNMT/MTHFR/MTRR RNA 관찰 | 부분 | 214명 비교는 두 이전 연구의 run-in 집단; 세포·사람 연결과 건강 매개효과 미검증. [S06](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0065744) |
| P06 | 아마씨 머핀/SDG → 종양 ERBB2 단백질 감소·Ki67/세포사멸 지표 변화 | POC 근거 충분 | 군 내 변화량; SDG 단독 효과·RNA/DNAm·생존 효과는 입증하지 않음. [S07](https://pubmed.ncbi.nlm.nih.gov/15897583/) |
| P07 | 자연 음식 엽산 가설 → 실제로는 엽산+B12 정제 → 선택 CpG/DMR 관찰 | 기각 대조 | 음식 개입 없음; 현재 HOXA10 좌위로 전이 불가; 부모 연구 골절 ITT CI가 1 포함. [S08](https://link.springer.com/article/10.1186/s13148-015-0154-5), [S09](https://pubmed.ncbi.nlm.nih.gov/25411293/) |
| P08 | 지중해식+견과/EVOO → CPT1B/GNAS 관련 정확 2CpG; 별도 부모 연구 심혈관 관찰 | 부분 | 36명 DNAm과 7,447명 결과를 매개효과로 연결하지 않음; 수정된 2018 보고 사용. [S10](https://pubmed.ncbi.nlm.nih.gov/29295516/), [S11](https://pubmed.ncbi.nlm.nih.gov/29897866/) |
| P09 | 우린 백차의 EGCG → 정제 EGCG 암 세포 promoter DNAm 감소·재발현 | 부분 | 식품 조성과 정제 세포 노출은 별도; 정확 cg ID·사람 암 예방 근거 없음. [S12](https://www.ars.usda.gov/ARSUserFiles/80400535/Data/Flav/Flav3.3.pdf), [S13](https://pubmed.ncbi.nlm.nih.gov/14633667/) |
| P10 | 같은 백차 조성 → 정제 EGCG → astrocyte PTGS2 단백질/PGE2 증가 | 기각 대조 | EGCG의 보편적 PTGS2 감소 주장을 기각하는 방향 대조; 사람 건강 효과 아님. [S14](https://pubmed.ncbi.nlm.nih.gov/15210717/) |

RNA, 단백질, 전역 DNAm, promoter 영역 DNAm, 정확 CpG DNAm을 각각 보존했다. 증가/감소/무유의 차이/미확인 방향도 구분한다. 연구 간 연결은 `cross_study_hypothesis`, 같은 연구의 평행 관찰은 해당 edge 상태로 표시한다. 두 논문 또는 두 POC가 독립 재현을 뜻하지 않으며 독립 반복 수는 `null`이다.

현재 50 CpG와 선택된 정확 4 CpG의 교집합은 0이다. 전체 전사체·EWAS의 교집합 결과는 아니며, 22개 패널 유전자의 canonical 매핑 영수증이 없어 canonical overlap은 모두 `null`이다. 전체 4,630개 음식·성분 조인 수 역시 검증하지 않았다.

파일:
- [pocs.json](pocs.json): 10건의 원래 음식/조리 상태, 성분 형태·용량, 종/조직, 디자인, n·기간, 분자 측정, 건강 관찰, 각 edge 출처, 효과/불확실성/반증.
- [expected_cards.json](expected_cards.json): 실제 API 담당자가 표시해야 하는 10개 의미상 카드 기대값. 특정 HTTP 경로나 구현을 가정하지 않는다.
- [negative_fixtures.json](negative_fixtures.json): 과도한 출력 주장 30개의 거부 기대값. 실제 문헌 음성 대조 3건과 구별한다.
- [validate.mjs](validate.mjs), [tests.mjs](tests.mjs): 패킷 일관성과 출력 경계 검사. 생물학적 정답률·외부 임상검증 도구는 아니다.
- [test_results.json](test_results.json), [execution.json](execution.json): V8 실제 실행 91/91 통과 및 실행 범위.
- [SOURCE_AUDIT.md](SOURCE_AUDIT.md): 원출처 확인 범위·공개 메타데이터 승인·미확인 권한/단위/표본 수.
- [pocs.schema.json](pocs.schema.json): 검토용 JSON Schema. 별도 JSON Schema 라이브러리는 실행하지 않았으며 도메인 검사는 JavaScript로 실행했다.
- [PLAN.md](PLAN.md): 구현 전 저장한 계획(커밋 `10ac91a198bc70c84ae6c34563b71de61c910f3e`).

실제 플랫폼 적용에서는 이 자료를 기존 담당 작업으로 가져와 세 단계 링크와 출처, 측정 종류, n/조직, 효과/한계를 함께 표시하고 기각 대조를 보존해야 한다. 카드 출력에 대해 기대값과 30개 부정 fixture를 실제 HTTP/화면 검사에 연결해야 한다. 이 작업은 자료와 검사 기대값을 제공했으며 API·화면을 수정하거나 시험하지 않았다.

재현용 Node 실행 명령은 `node docs/mechanistic_poc_20261011/tests.mjs`이다. 여기서는 Node/pytest/HTTP 실행이 가능한 로컬 경로가 없었으므로 이 명령을 실행하지 않았다. 저장된 결과는 `functions.exec`의 V8에서 실제 실행한 결과이다.
