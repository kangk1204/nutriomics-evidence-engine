# 기전 POC 10건 — 실행 전 계획

사용자 요청: 음식→실제 성분→발현 또는 메틸화→건강 관련 관찰 결과가 플랫폼에서 드러나도록 문헌/데이터 기반 시험사례 약10건을 검증한다. 새 실험·임상·모델훈련은 수행하지 않는다. 실제 API/UI 구현은 별도 담당 스레드 01a109e2-7d7f-7756-b0e5-0d022dc6f00f가 담당한다.

## 선정 범위

P01 브로콜리 새싹/SFN/상기도 발현 유도; P02 같은 계열의 오존 노출 POC 음성;
P03 농축환원 오렌지주스/hesperidin/백혈구 발현·혈관 지표;
P04 phenol-rich virgin olive oil/PBMC 염증 유전자 발현;
P05 코코아 크림/성분 혼합물/전역 메틸화와 별도 ex-vivo 발현;
P06 아마씨 머핀/SDG·lignan/ERBB2 단백질 발현·종양 생체표지;
P07 합성 folic acid+B12/DNAm 및 골절 예방 기각 대조;
P08 MedDiet+EVOO/견과류/정확2CpG와 별도 PREDIMED 건강 결과;
P09 brewed white tea/EGCG/암 세포 promoter demethylation;
P10 같은 식품 성분/EGCG/PTGS2 증가의 방향 기각 대조.

## 완료 기준

1. 10건 모두 food identity/preparation, native compound/form, edge별 1차 출처 DOI/PMID 또는 official DB URL, 종·설계·n·용량·기간·조직·표적·방향·효과와 결측 이유를 기록한다.
2. 충분 근거는 문헌에 실제 측정된 기전/관찰 edge의 인수인계 충분성이다. 완전 인과사슬이나 임상 효능 판정이 아니다. 충분/부분/기각 대조를 분리하고 모든 full-causal/clinical-qualified 값은 false로 유지한다.
3. RNA, protein expression, exact-CpG methylation, promoter-region methylation, global methylation을 분리한다. 어떤 RNA/단백질 결과도 DNAm으로 바꾸지 않는다.
4. 다른 연구·대상·조직의 결합은 cross-study hypothesis로 명시한다. 동일 trial의 별도 subset/report도 개인별 연결/mediation이 검증된 것으로 취급하지 않는다.
5. 실제50CpG frozen input과 selected assay targets만 대조한다. 전사체 전체3,422유전자 등의 전체 패널 조인은 수행하지 않았다. authoritative22gene mappings가 없어 canonical overlap은 미확인이다.
6. 증거 metadata는 사용자가 공개 제공을 승인한 새 사실 요약·식별자·출처 링크로 제한한다. 원문·그림·대형 upstream table·CTD raw sentence·개인별 데이터는 포함하지 않는다. 일반 OA/DB licence만으로 원자료 재배포를 허용하지 않는다.
7. API용 구조화 자료와 expected response/negative cases를 실제 V8에서 검사하고 GitHub의 별도 docs 경로에 불변 commit으로 저장·재조회한다. 플랫폼 HTTP/UI 검사나 Node 실행으로 주장하지 않는다.

남은 연결이 있는 POC는 빈 값을 추론해서 채우지 않는다. Mac 로컬 실행은 현재 노출 도구가 없어 차단 상태이고 다른 host/새 자격 경로를 사용하지 않는다. 기존94p 보고서 변경·API 배포는 이 작업에서 수행하지 않는다.
