[English](README.md) | **한국어**

# NutriOmics 식품과 분자 근거 연결

식품 성분, 화합물, 유전자, 질환 관계와 문헌 출처를 하나의 조회 구조로 연결하는 코드입니다. CTD를 정제해 고혈압 관련 근거를 구성하고, 식품 조성과 FDA 사용조건을 근거 종류별로 저장합니다.

[구축 결과와 입력 해시](docs/validated_snapshot.json) | [문헌 추출 평가](docs/qwen_drugprot_summary.json) | [통합 웹](https://github.com/kangk1204/nutriomics-db) | [통합 보고서, 열람 권한 필요](https://github.com/kangk1204/nutriomics-final-report)

## 구현 내용

- CTD 파일의 압축 무결성, 열 구조를 검사하고 Parquet으로 정제합니다.
- 식품, 성분, 유전자, 질환, 경로를 식별자로 연결합니다.
- 관계마다 PMID, 원자료, 종, 조직, 조건과 근거 종류를 보존합니다.
- 영양성분의 측정값, 계산값, 0, 결측을 구분합니다.
- SQLite 근거 DB에서 질환과 근거 종류별로 결과를 조회합니다.

초기 질환 범위는 일반 고혈압 `MESH:D006973`과 본태성 고혈압 `MESH:D000075222`입니다. 인간 화합물, 유전자 관계에는 종 ID `9606`을 사용합니다.

## 구축 규모

CTD는 2026년 9월 29일 생성본이며, 아래는 10월 1일 검증한 초기 고혈압 근거 DB입니다.

| 항목 | 건수 | 집계 단위 |
|---|---:|---|
| CTD 화합물, 유전자 원자료 | 3,171,202 | 전체 원자료 행 |
| CTD 직접 화합물, 질환 원자료 | 109,737 | 전체 원자료 행 |
| CTD 직접 유전자, 질환 원자료 | 34,315 | 전체 원자료 행 |
| 근거 DB의 노드 | 8,120 | 식품, 성분, 유전자, 질환, 경로 등의 식별 항목 |
| 근거 DB의 관계 | 426,922 | 조성, 문헌, 경로 관계 |
| 인용 기록 | 66,833 | 근거 DB의 인용 항목 |
| 식품 조성 기록 | 369,408 | 측정, 계산, 결측 상태를 포함한 식품, 성분 기록 |

근거 DB의 관계 수에는 식품 조성 관계가 포함됩니다. CTD 전체 원자료 규모, 고혈압 관련 부분집합과 [통합 DB의 후속 확장 규모](https://github.com/kangk1204/nutriomics-final-report)는 각각 집계합니다. 통합 보고서 저장소는 열람 권한이 필요합니다.

## 근거를 읽는 방법

| 근거 종류 | 담고 있는 정보 |
|---|---|
| 식품 조성 | 출처별 성분량, 단위와 측정 상태 |
| 직접 문헌 근거 | CTD가 문헌으로 연결한 화합물, 유전자, 질환 관계 |
| 추론 관계 | 직접 근거를 연결해 얻은 연관성 |
| 모델 예측 | 문헌 관계 후보와 예측 점수 |
| FDA 사용조건 | 성분의 규격, 용도, 사용조건 |

CTD의 화합물, 유전자 관계는 발현 변화 등 분자 반응을 포함합니다. 측정 Kd를 사용하는 결합력 예측은 [DearDTI KFRI](https://github.com/kangk1204/DearDTI_kfri)에서 수행합니다. 화학 구조의 확정 연결은 구조 식별자로 관리하고, 이름 기반 후보 연결은 검토 상태를 함께 저장합니다.

## 문헌 분석과 통합 웹

이 저장소에는 규칙 기반 추출과 Qwen2.5-7B-Instruct의 초기 비교, 문헌 서비스 연계 코드가 있습니다. DrugProt 개발 750편의 엄격한 관계 추출 평가에서 규칙 기반 F1은 **0.041**, Qwen F1은 **0.000**이었습니다. 생성 응답 726편과 메모리 오류 24편을 포함한 전체 분모로 계산했습니다.

이후 개발한 BiomedBERT 관계 분류, 개체 탐지와 문헌 검색, 요약 화면은 [NutriOmics DB의 문헌 플랫폼](https://github.com/kangk1204/nutriomics-db#문헌-분석-결과)에서 확인할 수 있습니다. 정답 개체를 제공한 관계 존재 예측과 전체 자동 추출의 평가 조건을 각각 제공합니다.

| 확인할 내용 | 파일 |
|---|---|
| CTD, 식품 DB 검증 결과 | [validated_snapshot.json](docs/validated_snapshot.json) |
| 규칙, Qwen 추출 결과 | [qwen_drugprot_summary.json](docs/qwen_drugprot_summary.json) |
| DrugProt 공식 평가기 결과 | [drugprot_official_qwen_evaluator.json](docs/drugprot_official_qwen_evaluator.json) |
| 문헌 서비스 연계 | [literature_service_integration.json](docs/literature_service_integration.json) |
| 재사용 코드 목록 | [literature_service_source_manifest.json](docs/literature_service_source_manifest.json) |

## 설치와 실행

Python 3.11 이상에서 설치합니다.

```sh
python -m pip install -e ".[dev]"
nutriomics-evidence --help
python -m pytest -q
```

CTD 파일을 준비한 뒤 실행합니다.

```sh
nutriomics-evidence ingest-ctd --source-dir /absolute/path/to/CTD --output-dir artifacts/ctd --source-registry artifacts/source-registry.json
nutriomics-evidence build-graph --input-dir artifacts/ctd --database artifacts/hypertension.sqlite
nutriomics-evidence validate --database artifacts/hypertension.sqlite
nutriomics-evidence query --database artifacts/hypertension.sqlite --disease MESH:D006973 --tier curated --limit 10
```

Parquet은 원자료 정제에, SQLite는 근거 조회에 사용합니다. 원자료, 생성 DB는 Git 밖의 연구 저장소에 보관하고, 이 저장소에는 코드, 스키마, 집계, 해시를 제공합니다.

## 출처와 사용 조건

CTD, 식품 조성 자료와 FDA 자료는 제공기관의 이용조건에 따라 수집, 분석합니다. 자료별 출처와 해시는 [구축 결과](docs/validated_snapshot.json)에 기록했습니다. 문헌 원문은 해당 문헌의 접근, 재사용 조건에 맞춰 보관합니다.

코드는 [MIT 라이선스](LICENSE)로 제공합니다. 외부 자료와 모델의 출처 및 이용조건은 [데이터와 소프트웨어 이용 안내](DATA_LICENSES.md)에 정리했습니다.
