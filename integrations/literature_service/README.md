# NutriOmics 문헌 자동수집·근거정리

Python 3.12 기반 `heuristic-v1` 내부 연구 서비스입니다. 생성형 모델 추론과 GPU를 사용하지 않습니다. 기존 6개 주제에서 2025년 이후 PubMed 초록과 명시적 재사용 라이선스가 확인된 Europe PMC OA XML을 수집합니다. 연구설계·핵심 원문·유전자·성분·결과 관계를 규칙으로 정리하며 모든 관계는 검수 전 후보입니다.

## 운영 서버와 화면

- 서버: `keunsoo@100.82.52.41` (`keunsoo-Z10PE-D16-WS`, Tailscale)
- 독립 프로젝트: `/home/keunsoo/projects/nutriomics-literature`
- API `127.0.0.1:8010`, Streamlit `127.0.0.1:8510`
- 저장소: 프로젝트 `runtime/data`, `raw`, `dictionaries`, `reports`, `backups`, `logs`

로컬 PowerShell에서 연결을 유지합니다.

```powershell
ssh -N -L 8010:127.0.0.1:8010 -L 8510:127.0.0.1:8510 keunsoo@100.82.52.41
```

브라우저에서 <http://127.0.0.1:8510>을 열고, API는 <http://127.0.0.1:8010/docs>에서 확인합니다. 검수 계정은 `runtime/private/reviewer-credentials.json`에 보관합니다. 비밀번호를 보고서나 코드 저장소에 넣지 않습니다.

## 설치·명령

```bash
uv sync --frozen --extra dev
export LITERATURE_HOME=/home/keunsoo/projects/nutriomics-literature/runtime
.venv/bin/python -m nutri_literature.cli init
.venv/bin/python -m nutri_literature.cli update-hgnc
.venv/bin/python -m nutri_literature.cli collect
.venv/bin/python -m nutri_literature.cli process --stage extract --limit 1000
.venv/bin/python -m nutri_literature.cli process --stage oa --limit 1000
.venv/bin/python -m nutri_literature.cli report
.venv/bin/python -m nutri_literature.cli backup
.venv/bin/python -m nutri_literature.cli status
.venv/bin/python -m nutri_literature.cli create-account researcher-name
.venv/bin/python -m nutri_literature.cli reset-password kangk
.venv/bin/python -m nutri_literature.cli prepare-gold --n 200
.venv/bin/python -m nutri_literature.cli evaluate reviewed-gold.json
```

`config/topics.json`의 주제·검색식·시작일을 수정하면 다음 실행에서 검색식 해시가 바뀌고 새 버전의 전체 기간을 다시 수집합니다. 변경된 검색식은 이전 버전의 증분 체크포인트를 재사용하지 않습니다. HGNC 갱신은 명시적 명령으로만 수행하고 원본·해시를 동결합니다. 규칙 소스는 SHA-256 버전으로 고정하며 worker 재시작 시 바뀐 규칙의 문헌을 재처리합니다. 사전 변경 후 `reprocess`로 후보를 다시 생성합니다. 실행 중인 worker와 같은 단계의 `process` 명령은 중복 실행 방지 잠금으로 차단됩니다. 수동 처리 예시는 해당 worker를 중지한 상태에서 사용합니다.

## 수집·검수 원칙

PubMed ESearch/EFetch 결과 수와 실제 PMID 수를 대조하며 1만 건을 넘는 검색은 기간 분할합니다. 분할 불가 또는 누락 발생 시 실패를 기록하고 체크포인트를 갱신하지 않습니다. 증분은 마지막 성공 시점에서 7일을 겹쳐 수정일 기준으로 조회하고, 출판일 범위는 별도 적용합니다. 초록·본문·추출은 각각 큐로 처리합니다. 본문 미공개와 라이선스 부적합은 통신 실패와 구분합니다.

원문·추출은 내용 해시와 문자 위치를 보존합니다. 자동 규칙 점수는 정확도 확률이 아닙니다. 승인 시 현재 원문·추출 버전·문장·검수자 신원을 확인합니다. 원문 또는 규칙 변경은 재검토가 필요하며 철회 논문은 확정 지도에서 제외됩니다. 리뷰·서론·선행연구 인용을 원 연구의 결과로 확정하지 않습니다. 동시 등장이나 다단계 그래프 연결을 인과 주장으로 바꾸지 않습니다.

공유 디스크의 지연을 줄이기 위해 재생성 가능한 수집·추출 중간 작업은 WAL `synchronous=NORMAL`을 사용하고, 수집 체크포인트와 검수 확정은 `FULL`로 저장합니다. 갑작스러운 전원 손실로 최근 중간 작업이 유실되면 큐에서 재처리합니다. [SQLite 동기화 설명](https://www.sqlite.org/pragma.html#pragma_synchronous).

한국어 화면은 구조화 항목과 원문 문장을 제공합니다. 불명확한 대상자 수·조직·용량·통계는 미확인으로 남깁니다. 초록과 공개 본문은 내부 검수 자료이며 공개 접근 자체를 재배포 허가로 간주하지 않습니다. 보고서도 내부 연구용입니다.

## 스케줄·복구

`scripts/cron_install.py`는 기존 crontab을 백업하고 이 서비스의 표시된 블록만 추가·갱신합니다. 설치 시 `service_watchdog.sh`가 supervisor를 실행합니다. API/UI와 OA·추출 worker 2개는 자동 재시작합니다. minutely tick은 Asia/Seoul 기준 매일14시 수집, 월요일15시 보고서, 일요일13시 본문 갱신, 매월1일12시 전체 대조, 매일16시 백업을 실행합니다. 지연된 작업은 최신 예정 시점으로 합치고 실패를 제한적으로 재시도합니다.

```bash
.venv/bin/python scripts/cron_install.py
bash scripts/service_watchdog.sh
.venv/bin/supervisorctl -c scripts/supervisord.conf status
```

백업은 SQLite 온라인 백업 API와 integrity_check를 사용합니다. 복원 전 supervisor를 중지한 뒤 검증된 백업을 **새 테스트 DB 경로**에 복원해 행 수와 integrity를 검사합니다. 운영 DB 교체는 백업을 보존한 상태에서 별도 작업으로 수행합니다. 실서버 재부팅은 다른 작업에 영향을 주므로 자동 검증에서는 이 서비스의 supervisor만 재시작합니다.

## 검증과 성능 보고

```bash
.venv/bin/python -m pytest -q
```

테스트의 합성 문장은 동작 검증용이며 추출 정확도 측정자료가 아닙니다. 200편 정답셋은 전문가가 작성·검수해야 합니다. 100편 개발/100편 봉인 평가와 40편 교차 검수를 준비하며 미검수 정답셋에서는 성능을 계산하지 않습니다. 유전자 탐지·ID 정규화·관계 추출 지표와 분모를 각각 보고합니다. 목표 정밀도90%·재현율70%는 측정 전 보장하지 않습니다.

최초 배포의 전문가 검수, 실제 서버 재부팅, 7일 연속 가동 검증 상태는 `IMPLEMENTATION_STATUS.md`에 기록합니다. 데이터·실행·리포트 수와 scientific accuracy를 구분합니다.

cron의 독립 5분 health-check가 API와 UI를 관측하며 `/api/v1/soak-status`와 `soak-status` CLI로 결과를 조회합니다. 최근 실제 7일과 최소2016개 관측, 실패 없음·10분 초과 공백 없음이 충족되어야 passed를 표시합니다. 이전 실패 기록도 보존합니다. 관측값은 재부팅 시험이나 전문가 정확도 검증을 대신하지 않습니다.

정답 표기는 `gold.json`의 빈 항목에 전문가가 독립적으로 작성합니다. 표기자는 자동 예측 파일을 참조하지 않습니다. 개발 담당자는 개발용 100편만 사용하고 평가용 100편의 정답은 별도 검수 담당자가 보관합니다. 원문·섹션·종 판별 메타데이터·분할은 `frozen_inputs.json`에 동결됩니다. 규칙 보정 후 그 입력으로 새 예측 실행을 생성하며, 기존 정답이나 분할을 수정하지 않습니다.

```bash
.venv/bin/python -m nutri_literature.cli evaluate runtime/evaluation/COHORT/gold.json --split development
.venv/bin/python -m nutri_literature.cli predict-gold runtime/evaluation/COHORT/frozen_inputs.json
.venv/bin/python -m nutri_literature.cli evaluate runtime/evaluation/COHORT/gold.json --prediction-run runtime/evaluation/COHORT/PREDICTION_RUN.json --split heldout
```

`COHORT`와 `PREDICTION_RUN.json`은 각 명령이 반환하는 실제 경로로 바꿉니다. 평가 입력·예측 해시는 DB 감사 기록에 고정되므로 평가 자료를 옮길 때 해당 DB 백업도 보존합니다. 미검수 개발/평가 항목은 해당 분할의 성능 계산을 차단합니다. `scripts/validate_deployment.py`는 실제 원본 해시·문자 위치·DB와 백업 복원·API/UI 상태를 검사해 `runtime/validation/deployment.json`에 기록합니다.

## 재사용과 출처

PubMed 파싱·PMID 완전성 검사·원본 해시 패턴은 기존 `nutriomics-evidence-engine/scripts/fetch_public_evidence.py`를 바탕으로 보강했습니다. API 페이지 조회, 증분 상태, 검수 서비스와 운영 기능은 본 서비스에 구현합니다. 공식 출처는 [PubMed E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/), [Europe PMC API](https://europepmc.org/RestfulWebService), [HGNC](https://www.genenames.org/download/)입니다.
