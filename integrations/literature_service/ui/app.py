"""Internal Korean review workspace. Start with streamlit run ui/app.py."""

import html
import math
import os

import plotly.graph_objects as go
import requests
import streamlit as st

API = os.environ.get("LITERATURE_API_URL", "http://127.0.0.1:8010").rstrip("/")
st.set_page_config(page_title="문헌 근거 검수", page_icon="📚", layout="wide")


def api(path, method="GET", *, params=None, body=None, download=False):
    headers = {}
    if st.session_state.get("token"):
        headers["Authorization"] = "Bearer " + st.session_state["token"]
    try:
        response = requests.request(method, API + path, params=params, json=body, headers=headers, timeout=30)
        if response.status_code == 401:
            st.session_state.pop("token", None)
            st.session_state.pop("username", None)
        if response.status_code >= 400:
            try:
                message = response.json().get("detail", "요청을 처리하지 못했습니다.")
            except ValueError:
                message = "요청을 처리하지 못했습니다."
            st.error(str(message))
            return None
        return response.content if download else response.json()
    except requests.RequestException:
        st.error("문헌 API에 연결하지 못했습니다. 서버 실행 상태와 SSH 포워딩을 확인하세요.")
        return None


def render_links(links):
    for key, url in links.items():
        if url.startswith(("https://pubmed.ncbi.nlm.nih.gov/", "https://doi.org/", "https://europepmc.org/")):
            st.link_button({"pubmed": "PubMed", "doi": "DOI", "europe_pmc": "Europe PMC"}.get(key, key), url)


def render_summary(result):
    # The engine result contains exact excerpts and structured fields, never generated prose.
    summary = result.get("summary", result) if isinstance(result, dict) else result
    if not summary:
        st.info("아직 요약이 완료되지 않았습니다.")
    elif isinstance(summary, dict):
        for key, label in [("method", "연구설계"), ("results", "주요 결과"), ("limitations", "한계")]:
            st.caption(label)
            value = summary.get(key, "미확인")
            excerpts = value if isinstance(value, list) else [value]
            if not excerpts:
                st.text("미확인")
            for excerpt in excerpts:
                if isinstance(excerpt, dict):
                    st.text(str(excerpt.get("text", excerpt.get("value", "미확인"))))
                    if "start" in excerpt and "end" in excerpt:
                        st.caption(f"원문 문자 위치 [{excerpt['start']}, {excerpt['end']})")
                else:
                    st.text(str(excerpt))
        if isinstance(result, dict) and result.get("context"):
            labels = {
                "study_design": "연구 유형",
                "participants": "대상자 수",
                "organism": "연구 대상 종",
                "tissue": "조직",
                "dose": "용량",
                "response_time": "관찰 시점",
                "comparator": "비교군",
            }
            with st.expander("추출된 연구 특성"):
                for key, label in labels.items():
                    value = result["context"].get(key, "미확인")
                    st.caption(label)
                    if isinstance(value, dict):
                        st.text(str(value.get("value", "미확인")))
                        if value.get("quote"):
                            st.code(value["quote"], language=None, wrap_lines=True)
                    else:
                        st.text(str(value))
        st.caption("규칙으로 선택한 원문 인용입니다. 통계적·인과적 해석은 검수자가 확인합니다.")
    else:
        st.text(str(summary))


def detail(paper_id):
    item = api(f"/api/v1/papers/{paper_id}")
    if not item:
        return
    st.subheader(item["title"])
    if item["retracted"]:
        st.error("철회 문헌입니다. 검수된 Evidence Map에서 제외됩니다.")
    st.caption(f"PMID {item['pmid']} · 출판일 {item.get('pub_date') or '미확인'} · OA {item['oa_status']}")
    render_links(item["official_links"])
    tabs = st.tabs(["구조화 요약", "원문·출처", "유전자·성분", "관계·검수 이력"])
    with tabs[0]:
        current = next((e for e in item["extractions"] if e["current_valid"]), None)
        if current:
            st.caption(f"엔진 {current['engine_version']} · 사전 {current['dictionary_version']}")
            render_summary(current["result"])
        elif item.get("summary_status") == "stale":
            st.warning(
                "원문 또는 추출 규칙이 변경되어 기존 요약을 현재 결과로 표시하지 않습니다. 재처리 대기 중입니다."
            )
        else:
            st.info("추출 대기 중입니다.")
    with tabs[1]:
        for source in item["sources"]:
            with st.expander(f"{source['kind']} · {source['retrieved_at']}"):
                st.text(
                    f"원본 SHA-256: {source['raw_hash']}\n텍스트 SHA-256: {source['text_hash']}\n라이선스: {source.get('license') or '미확인'}"
                )
                if source["url"].startswith("https://"):
                    st.text("수집 출처: " + source["url"])
                st.code(source["text_content"], language=None, wrap_lines=True)
    with tabs[2]:
        if item["mentions"]:
            st.dataframe(
                [
                    {k: m.get(k) for k in ("kind", "text", "normalized_id", "start", "end", "status")}
                    for m in item["mentions"]
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("탐지된 후보가 없습니다.")
    with tabs[3]:
        for edge in item["assertions"]:
            with st.expander(f"{edge['subject']} → {edge['object']} · {edge['display_status']}"):
                if not edge["current_valid"]:
                    st.warning("과거 추출·검수 이력입니다. 현재 근거로 사용할 수 없습니다.")
                st.text(edge["predicate"])
                st.code(edge["quote"], language=None, wrap_lines=True)
                st.caption(f"문자 위치 [{edge['start']}, {edge['end']}) · 규칙 {edge['rule_id']}")
                if edge.get("review"):
                    st.json(edge["review"])


st.title("문헌 근거 검수")
st.caption("heuristic-v1 · 한국어 구조화 요약과 원문 인용 · 자동 후보는 연구자의 확인이 필요합니다.")
with st.sidebar:
    st.subheader("검수자 계정")
    if st.session_state.get("token"):
        st.text(st.session_state.get("username", "로그인됨"))
        if st.button("로그아웃", width="stretch"):
            api("/api/v1/auth/logout", "POST")
            st.session_state.pop("token", None)
            st.session_state.pop("username", None)
            st.rerun()
    else:
        with st.form("login"):
            username = st.text_input("계정")
            password = st.text_input("비밀번호", type="password")
            submitted = st.form_submit_button("로그인", width="stretch")
        if submitted:
            session = api("/api/v1/auth/login", "POST", body={"username": username, "password": password})
            if session:
                st.session_state["token"] = session["access_token"]
                st.session_state["username"] = session["username"]
                st.rerun()
        st.caption("계정은 서버 CLI에서 개인별로 생성합니다.")
    st.divider()
    view = st.radio("작업", ["문헌 검색", "논문별 요약", "Evidence Map", "검수 대기열", "실행 상태·리포트"])
    topics = api("/api/v1/topics")
    choices = {"전체 주제": None}
    if topics:
        choices.update({t["name"]: t["topic_id"] for t in topics["items"] if t["enabled"]})
    topic_label = st.selectbox("주제", list(choices))
    topic = choices[topic_label]
    st.caption("2025년 이후 문헌 · 초록 및 이용 가능한 공개 XML")

if view == "문헌 검색":
    query = st.text_input("제목·초록 검색", placeholder="gene expression, hypertension, omega-3…")
    page = st.number_input("페이지", min_value=1, value=1, step=1)
    listing = api(
        "/api/v1/papers", params={"q": query, "topic": topic, "limit": 20, "offset": (page - 1) * 20}
    )
    if listing:
        st.caption(f"고유 문헌 {listing['total']:,}편 · 현재 {len(listing['items'])}편")
        for paper in listing["items"]:
            with st.expander(f"{paper['title']} · PMID {paper['pmid']}"):
                st.text(f"출판일 {paper.get('pub_date') or '미확인'} · OA {paper['oa_status']}")
                if paper["retracted"]:
                    st.error("철회 문헌")
                if paper.get("summary_status") == "stale":
                    st.warning("원문 또는 추출 규칙이 변경되었습니다. 최신 요약 재처리 대기 중입니다.")
                else:
                    render_summary(paper.get("summary"))
                st.caption(f"요약 상세에서 사용할 문헌 ID: {paper['paper_id']}")
                render_links(paper["official_links"])
elif view == "논문별 요약":
    paper_id = st.number_input("문헌 ID", min_value=1, value=1, step=1)
    if st.button("문헌 열기", type="primary"):
        st.session_state["detail_id"] = paper_id
    if st.session_state.get("detail_id"):
        detail(st.session_state["detail_id"])
elif view == "Evidence Map":
    filters = st.columns(2)
    with filters[0]:
        statuses = {
            "연구자 확인 근거": "approved",
            "자동 후보": "candidate",
            "재검토": "needs_review",
            "전체 현재 관계": "all",
        }
        status = statuses[st.selectbox("근거 상태", list(statuses))]
    with filters[1]:
        gene = st.text_input("유전자 필터", placeholder="예: NOS3 또는 HGNC ID")
    mapping = api(
        "/api/v1/evidence-map", params={"topic": topic, "gene": gene or None, "status": status, "limit": 200}
    )
    st.info("각 연결은 한 문헌의 원문 근거입니다. 여러 연결을 합쳐 식이 인과 효과로 해석하지 않습니다.")
    if mapping and mapping["edges"]:
        nodes = mapping["nodes"]
        positions = {
            n["id"]: (math.cos(2 * math.pi * i / len(nodes)), math.sin(2 * math.pi * i / len(nodes)))
            for i, n in enumerate(nodes)
        }
        figure = go.Figure()
        for reviewed, label, color in [(False, "자동 후보", "#d09b3c"), (True, "연구자 확인", "#26756a")]:
            x, y = [], []
            for edge in mapping["edges"]:
                if edge["is_reviewed"] != reviewed:
                    continue
                start, end = positions[edge["subject"]], positions[edge["object"]]
                x.extend([start[0], end[0], None])
                y.extend([start[1], end[1], None])
            if x:
                figure.add_trace(
                    go.Scatter(
                        x=x,
                        y=y,
                        mode="lines",
                        name=label,
                        line={"color": color, "width": 2, "dash": "solid" if reviewed else "dot"},
                        hoverinfo="skip",
                    )
                )
        figure.add_trace(
            go.Scatter(
                x=[positions[n["id"]][0] for n in nodes],
                y=[positions[n["id"]][1] for n in nodes],
                mode="markers+text",
                name="요소",
                text=[html.escape(n["label"]) for n in nodes],
                textposition="top center",
                hoverinfo="text",
                marker={"color": "#253d59", "size": 12},
            )
        )
        figure.update_layout(
            height=520,
            margin={"t": 35, "b": 35, "l": 50, "r": 50},
            xaxis={"visible": False},
            yaxis={"visible": False},
            plot_bgcolor="#f8fafb",
        )
        st.plotly_chart(figure, width="stretch")
        st.caption(
            f"관계 {mapping['total']:,}건 중 {len(mapping['edges'])}건 표시 · 문헌 수와 관계 수는 다릅니다."
        )
        st.dataframe(
            [
                {
                    k: edge[k]
                    for k in ("paper_id", "pmid", "subject", "predicate", "object", "status", "quote")
                }
                for edge in mapping["edges"]
            ],
            hide_index=True,
            width="stretch",
        )
    elif mapping:
        st.info("선택한 조건의 현재 관계가 없습니다.")
elif view == "검수 대기열":
    if not st.session_state.get("token"):
        st.warning("문헌과 후보는 열람할 수 있습니다. 승인·수정·기각을 기록하려면 로그인하세요.")
    statuses = {"자동 후보": "candidate", "재검토": "needs_review", "승인 이력": "approved"}
    status = statuses[st.selectbox("대기열 상태", list(statuses))]
    page = st.number_input("검수 페이지", min_value=1, value=1, step=1)
    queue = api(
        "/api/v1/evidence-map",
        params={"topic": topic, "status": status, "limit": 20, "offset": (page - 1) * 20},
    )
    if queue:
        st.caption(f"관계 {queue['total']:,}건")
        for edge in queue["edges"]:
            with st.expander(f"PMID {edge['pmid']} · {edge['subject']} → {edge['object']}"):
                st.text(edge["title"])
                st.code(edge["quote"], language=None, wrap_lines=True)
                st.caption(
                    f"위치 [{edge['start']}, {edge['end']}) · 규칙 {edge['rule_id']} · {edge['engine_version']}"
                )
                st.text(f"텍스트 SHA-256: {edge['text_hash']}")
                st.json(edge["payload"], expanded=False)
                render_links(edge["official_links"])
                with st.form("review_" + edge["assertion_id"]):
                    decisions = {"승인": "approved", "기각": "rejected", "관계 수정 후 승인": "corrected"}
                    decision = st.selectbox("판단", list(decisions))
                    subject = st.text_input("주어", value=edge["subject"])
                    predicate = st.text_input("관계", value=edge["predicate"])
                    target = st.text_input("목적어", value=edge["object"])
                    comment = st.text_area("검수 메모 · 수정 시 사유 필수")
                    submitted = st.form_submit_button(
                        "판단 저장", disabled=not bool(st.session_state.get("token"))
                    )
                if submitted:
                    body = {
                        "assertion_id": edge["assertion_id"],
                        "decision": decisions[decision],
                        "comment": comment,
                    }
                    if body["decision"] == "corrected":
                        body["corrected_payload"] = {
                            "subject": subject,
                            "predicate": predicate,
                            "object": target,
                        }
                    result = api("/api/v1/reviews", "POST", body=body)
                    if result:
                        st.success("개인 계정과 원문 버전에 연결해 판단을 저장했습니다.")
                        st.rerun()
elif view == "실행 상태·리포트":
    soak = api("/api/v1/soak-status")
    if soak:
        st.caption(
            f"7일 운영 관측: {soak['status']} · 관측 {soak['samples']}회 · 실제 경과 {soak.get('elapsed_hours', 0)}시간"
        )
    runs = api("/api/v1/runs")
    if runs:
        cols = st.columns(4)
        for col, key, label in zip(
            cols,
            ["papers", "summarized_papers", "oa_papers", "retracted_papers"],
            ["고유 문헌", "요약 문헌", "공개 본문 문헌", "철회 문헌"],
        ):
            col.metric(label, f"{runs['counts'][key]:,}편")
        st.subheader("실행 기록")
        st.dataframe(runs["items"], hide_index=True, width="stretch")
        with st.expander("예약 작업·재처리 대기열"):
            st.json({"jobs": runs["jobs"], "queue": runs["queue"]})
    reports = api("/api/v1/reports")
    st.subheader("주간 리포트")
    if reports:
        for report in reports["items"]:
            with st.expander(f"{report['period_start']} ~ {report['period_end']} · {report['generated_at']}"):
                st.text("스냅샷 SHA-256: " + report["snapshot_hash"])
                st.json(report["snapshot"], expanded=False)
                for name, path in report["downloads"].items():
                    if st.button(f"{name.upper()} 파일 준비", key=report["report_id"] + name):
                        content = api(path, download=True)
                        if content is not None:
                            suffix = {"html": "html", "markdown": "md", "csv": "csv"}[name]
                            st.download_button(
                                f"{name.upper()} 내려받기",
                                content,
                                file_name=f"report-{report['report_id']}.{suffix}",
                                key="download_" + report["report_id"] + name,
                            )
