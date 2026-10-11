# 구현·실행 결과 — 근거 보강 v2

[PLAN.md](PLAN.md)와[plan.json](plan.json)을 먼저 `bfb8558ae6b7fcb87192af1135c2b295d26371f2`에 저장한 뒤, API와 독립된 문서용 감사 도구를 구현·실행했다. 계획과 구현 완료 상태는 [execution.json](execution.json)에서 분리했다.

## 실제 실행

- 원보고서의 **50개 CpG 전체**와 동결 선택 graph receipt의 **예시6경로 전체**에 감사 함수를 실행했다. 원본 serving DB나4,630개 extension 행을 실행 입력으로 읽은 것은 아니다.
- 39개 위치 주석·22개 native 유전자·11개 미배정, 보고 SNP표시8개·재현 결측4개를 회계했다. SNP표시는 원보고서 주석이고 새로운 probe QC 통과/탈락 판정이 아니다.
- 22개 authoritative canonical-ID 매핑 receipt는 입력에 없다. **verified mapping0은 입력에 확인된 매핑이0이라는 뜻**이다. 유전자 존재가0이거나22개가 모두 잘못됐다는 뜻이 아니다.
- native name 겹침은0/6, canonical ID 겹침은 **미확인(null)**이다. 이름 비교 결과를 최종 ID 조인으로 바꾸지 않는다.
- EWAS50개는 모두 **미조회**이다. 서비스 home timeout/download503은 개별50개 nohit 결과가 아니다.
- 경로6건은 음식1개·성분1개·조성 측정1건을 공유한다. 중첩 반응3건·공동처치2건의 조건을 유지했다.
- 선택된11근거 기록의 PMID6개를 독립 재현 수로 바꾸지 않았다. M01/M02/M03/M04/P01은 같은GSE222595/source2023를 공유한다. 확인된 용량·기간 기록1건을 용량 반응 실험으로 세지 않았다.
- 전체4,630개 linked/unverified 건수는 null로 유지했다. 소규모 개발 검사는 전체4,630개 연구 범위를 줄이지 않는다.

## 구현 파일

| 파일 | 동작 |
|---|---|
| [audit.mjs](audit.mjs) | exact ID mapping receipt/ambiguity, native form·food context·quantity, source grouping, lookup state, export readiness 진단 |
| [run_audit.mjs](run_audit.mjs) | 제공된 유한 JSON을 읽고 결과를 stdout에 출력; network/DB write/API/qualification 없음 |
| [audit_input.json](audit_input.json) | 실제 문서 입력과 불명확성; 원 CTD 문장/대형 원자료는 복제하지 않음 |
| [audit_result.json](audit_result.json) | 현재 실행의50개 위치 및6개 경로별 gap/warning |
| [gene_mapping_requests.csv](gene_mapping_requests.csv) | native22심볼 각각의 source-verified stable ID 요청 |
| [panel_gaps.csv](panel_gaps.csv) | 50개 CpG 전부의 주석·매핑·probe/EWAS 상태 |
| [tests.mjs](tests.mjs)·[test_results.json](test_results.json) | 합성 code QA57건; 입체/염/부위/조리/단위/검출한계/정성/종/권리/중복/오류상태/독립성 |
| [execution.json](execution.json) | 수행·미수행·blocked·정확한 source blob 및 분모 |

**V8에서57/57 코드 검사 통과.** 실제 frozen 문서 입력도 실행했다. 테스트 fixture는 코드 경계 검사이며 생물학적 음성·독립 임상/추출 정확도 평가가 아니다. Node entrypoint는 제공했지만 Mac 연결이 없어 native Node 실행은 미검증이다. exact-native 상태값만으로는 조인하지 않고 양쪽 제공 native 구조/형태 receipt를 비교한다. 미배정 CpG나 food context 결측은 unknown으로 유지한다. source receipt의 내용/형식은 검사하지만 원본 대형 파일 byte를 다시 해시하지 않았으며, 그 사실을 결과에 명시한다.

복구된 동일 Mac에서 유한 입력 확인을 위한 진입점은 `node tests.mjs`와`node run_audit.mjs`이다. 자동 실행·환경 설치·자격 입력·원자료 다운로드·다른 host 접속은 포함하지 않는다.

## 과학적·운영상 미완료

전체4,630개 테이블 대조, 정확한 HGNC/GPL/probe QC/원 보충표·외부 EWAS 조인, FISHGASTRO28/31명 및 개인 임상 crosswalk는 해결되지 않았다. 기존 failed/음성 결과나 학습 중지 상태를 바꾸지 않았다. 내부 graph·현재 패널·외부 관찰/clock 연구의 조합이 음식→현재CpG→건강효과 전체를 입증하지 않는다.

라이선스 미확인/조건부 출처의 dataset export를 readiness 진단에서 막으며, **실제 공개·dataset export·권한 변경은 없다**. 공식 DB의 일반 license 확인은 해당 원자료 artifact의 권리·원천 provenance 검증을 대체하지 않는다.

기존 점수 코드의 PMID count와 dose/duration presence는 기술된 입력 지표로 남긴다. 독립 재현이나 용량 반응 실험이라는 결론으로 승격하지 않도록 별도의 감사 상태를 구현했으며 API 점수 코드는 수정하지 않았다.

API 소유자 `01a109e2-7d7f-7756-b0e5-0d022dc6f00f`에게 전달 가능한 문서·코드·검사 결과다. **94쪽 보고서/API 적용과 독립 실증 평가는 not applied/not evaluated**이다.

## 별도 담당 인수인계 상태

부모 스레드가 API 담당의31경로·108검사·109HTTP 확인, 전체4,630개 중 공개허용 정확일치53개, 공개 version2 유지 및 동일Site 임시 write credential 갱신 승인 대기를 전달했다. 본 작업에서 이 API 검사를 재실행하거나 배포하지 않았다. 보고서 `libfile_e38b950e12988191b13fd483e4041eac`·증빙 `libfile_d8cc1d5ae2348191b719d4d3d58fc81d`도 전달된 별도 산출물이며 본 감사 코드의 검증 영수증과 구별한다.

사용자가 농진청 사용목적 **학술연구·교육자료 활용**, 직업군 **학술연구 관련 종사자**의 제출을 승인했다. 본 과학 근거 감사 작업에서는 해당 신청서를 제출하지 않았다. 이 승인만으로 개별 DB의 원자료 재배포 권리가 확인되는 것은 아니다.
