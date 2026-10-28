import datetime as dt
import json
import os

import pandas as pd
import streamlit as st
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from dotenv import load_dotenv
from openai import OpenAI

from chunks import FACILITY, MEMBERSHIP, build_chunks
from store import build_collection, resolve_version, search

load_dotenv()


def setting(name, default=None):
    """로컬은 .env, Streamlit Cloud는 st.secrets에서 읽는다."""
    if os.getenv(name):
        return os.getenv(name)
    try:
        return st.secrets[name]
    except Exception:
        return default


API_KEY = setting("OPENAI_API_KEY")
CHAT_MODEL = setting("OPENAI_CHAT_MODEL", "gpt-5.6-luna")
EMBED_MODEL = setting("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

st.set_page_config(page_title="RAG 메타데이터 데모", layout="wide")
st.title("메타데이터가 있으면 RAG가 뭐가 달라질까?")

if not API_KEY or API_KEY.startswith("sk-your"):
    st.error(".env(로컬) 또는 Streamlit secrets(배포)에 OPENAI_API_KEY를 넣어주세요.")
    st.stop()


@st.cache_resource(show_spinner="요금표 청크들을 벡터DB에 저장하는 중…")
def get_collection(api_key, model):
    ef = OpenAIEmbeddingFunction(api_key=api_key, model_name=model)
    return build_collection(ef)


col = get_collection(API_KEY, EMBED_MODEL)
llm = OpenAI(api_key=API_KEY)


def version_label(effective_from):
    """20260901 → '9월 요금표'"""
    return f"{effective_from // 100 % 100}월 요금표"


with st.sidebar:
    st.subheader("설정")
    k = st.slider("찾아올 청크 개수", 1, 8, 3)
    st.caption(f"임베딩 `{EMBED_MODEL}` · LLM `{CHAT_MODEL}` · 저장된 청크 {col.count()}개")

st.markdown(
    "한빛스포츠센터 요금표가 **9월 1일에 바뀌었습니다.** 챗봇의 DB에는 **1월 요금표와 9월 요금표가 둘 다** 들어 있어요. "
    "두 문서는 거의 똑같아서, 그냥 검색하면 챗봇이 옛 요금을 말할 수 있습니다.\n\n"
    "그래서 문서 청크마다 **메타데이터**로 '어느 파일인지', '언제부터 적용되는지'를 붙여두고, "
    "질문할 때 이 메타데이터로 **맞는 요금표만 골라** 봅니다."
)
st.markdown("📄 PDF → ✂️ 청크로 나누기 → 🏷️ 메타데이터 붙이기 → 🗄️ 벡터DB에 저장 → ❓ 질문 → 🔎 메타데이터로 거르고 비슷한 청크 찾기 → 💬 답변")

with st.expander("용어가 낯설다면"):
    st.markdown(
        "- **청크**: 긴 문서를 검색하기 좋게 잘게 나눈 한 덩어리. 여기서는 요금표 한 줄이 청크 하나입니다.\n"
        "- **메타데이터**: 청크에 붙이는 부가 정보. 여기서는 `source`(파일 이름)와 `effective_from`(시행일) 두 개입니다.\n"
        "- **임베딩**: 문장을 숫자 목록(벡터)으로 바꾼 것. 뜻이 비슷한 문장은 비슷한 숫자가 됩니다.\n"
        "- **벡터DB (Chroma)**: 청크·메타데이터·벡터를 함께 저장하고, 질문과 비슷한 청크를 찾아주는 DB입니다.\n"
        "- **필터**: 검색할 때 메타데이터 조건(예: 9월 요금표만)으로 청크를 미리 거르는 것입니다."
    )

tab_search, tab_doc, tab_db = st.tabs(["① 질문해보기", "② 바뀐 요금표 비교", "③ DB에 저장된 모습"])

# ② 바뀐 요금표 비교
def doc_location(key):
    """청크 id 뒷부분(member_수영 등)을 사람이 읽는 문서 위치로 바꾼다."""
    kind, _, item = key.partition("_")
    if kind == "member":
        return f"1. 회원권 요금 · {MEMBERSHIP[item][0]}"
    if kind == "facility":
        return f"2. 부대시설 요금 · {FACILITY[item][1][0]}"
    return {"intro": "도입 안내문", "discount": "3. 할인 규정", "revision": "3. 요금 개정 안내"}[kind]


with tab_doc:
    ids, docs, metas = build_chunks()
    by_key = {}
    for i, d in zip(ids, docs):
        version, key = i.split("_", 2)[1], i.split("_", 2)[2]
        by_key.setdefault(key, {})[version] = d
    rows = [{"문서 위치": doc_location(key), "1월 요금표": v["v1"], "9월 요금표": v["v2"],
             "변경": "변경" if v["v1"] != v["v2"] else ""}
            for key, v in by_key.items()]
    changed = [r for r in rows if r["변경"]]
    st.markdown(f"두 요금표는 {len(rows)}줄 중 **{len(changed)}줄만** 다릅니다. "
                "나머지는 글자까지 똑같아서, 청크 내용만 보고는 어느 요금표인지 알 수 없어요.")
    st.caption("1월 요금표 = 이용요금표.pdf (2026-01-01 시행) · 9월 요금표 = 이용요금표_개정.pdf (2026-09-01 시행)")
    show_all = st.checkbox("바뀌지 않은 줄도 보기")
    df = pd.DataFrame(rows if show_all else changed)
    st.dataframe(
        df.style.apply(lambda r: ["background-color: rgba(255,200,0,.25)" if r["변경"] else ""] * len(r), axis=1),
        use_container_width=True, hide_index=True,
    )

# ③ DB에 저장된 모습
with tab_db:
    st.markdown("벡터DB에는 청크 하나마다 **id · document(본문) · metadata · embedding(벡터)** 이 함께 저장됩니다.")
    st.code(
        """collection.add(
    ids=["fee_v2_member_수영", ...],
    documents=["[회원권 요금] 수영 (자유수영): 1개월 85,000원, ...", ...],
    metadatas=[{"source": "이용요금표_개정.pdf", "effective_from": 20260901}, ...],
)  # embeddings는 embedding_function이 documents로 자동 생성""",
        language="python",
    )
    st.info("메타데이터는 source(출처)와 effective_from(시행일) 두 개뿐입니다. "
            "새 요금표가 나오면 청크를 추가만 하면 되고, 기존 청크는 고치지 않아요. "
            "날짜는 Chroma에서 크기 비교가 되도록 YYYYMMDD 정수로 저장합니다.")

    got = col.get(include=["documents", "metadatas", "embeddings"])
    table = []
    for i, d, m, e in zip(got["ids"], got["documents"], got["metadatas"], got["embeddings"]):
        table.append({"id": i, "document": d, **m,
                      "embedding (앞 4개)": ", ".join(f"{x:.4f}" for x in e[:4]) + ", …",
                      "차원": len(e)})
    db_df = pd.DataFrame(table).sort_values(["effective_from", "id"])
    pick = st.radio("source", ["전체", *db_df["source"].unique()], horizontal=True)
    if pick != "전체":
        db_df = db_df[db_df["source"] == pick]
    st.dataframe(db_df, use_container_width=True, hide_index=True)

    with st.expander("청크 하나를 JSON으로 보기"):
        one = st.selectbox("id", got["ids"])
        idx = got["ids"].index(one)
        st.json({"id": one, "document": got["documents"][idx], "metadata": got["metadatas"][idx],
                 "embedding": f"[{', '.join(f'{x:.4f}' for x in got['embeddings'][idx][:8])}, … ] "
                              f"({len(got['embeddings'][idx])}차원)"})

# ① 질문해보기
SCENARIOS = [
    {"q": "수영 1개월 얼마야?", "point": "메타데이터를 안 쓰면 1월·9월 요금이 섞여요", "expect": "85,000원"},
    {"q": "8월 15일에 등록하면 헬스 1개월 요금은?", "point": "'항상 오늘 기준'은 과거 등록일을 못 맞춰요",
     "expect": "55,000원"},
    {"q": "회원은 주차 무료야?", "point": "숫자가 아니라 규정 문장이 바뀐 경우", "expect": "2시간"},
]
EXPECT = {s["q"]: s["expect"] for s in SCENARIOS}

FILTER_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": ["string", "null"],
                 "description": "요금 기준이 되는 날짜(등록일 등), YYYY-MM-DD. 질문에 날짜가 없으면 null"},
    },
    "required": ["date"],
    "additionalProperties": False,
}


def run_scenario(q):
    st.session_state.q = q


def is_correct(text, expect):
    """답변에 정답이 들어 있는지. 쉼표·공백·'원' 표기 차이는 무시한다."""
    norm = lambda s: s.replace(",", "").replace(" ", "").replace("원", "")
    return norm(expect) in norm(text)


@st.cache_data(show_spinner="질문에서 날짜를 찾는 중…")
def extract_filter(question, today):
    """셀프 쿼리: LLM이 질문에서 기준일을 뽑는다. 같은 질문은 다시 호출하지 않는다."""
    resp = llm.responses.create(
        model=CHAT_MODEL,
        instructions=f"오늘은 {today}이다. 질문에서 요금 기준이 되는 날짜(등록일 등)를 뽑는다. "
                     "연도가 없으면 오늘을 기준으로 가장 자연스러운 연도를 쓴다.",
        input=question,
        text={"format": {"type": "json_schema", "name": "search_filter",
                         "schema": FILTER_SCHEMA, "strict": True}},
    )
    return json.loads(resp.output_text)


def date_where(day):
    """기준일 → (where, 고른 버전). 시행 중인 버전이 없으면 (None, None)."""
    version = resolve_version(col, int(day.strftime("%Y%m%d")))
    if version is None:
        return None, None
    return {"effective_from": version["effective_from"]}, version


@st.cache_data(show_spinner=False)
def answer(question, documents):
    context = "\n".join(f"[{n}] {d}" for n, d in enumerate(documents, 1))
    resp = llm.responses.create(
        model=CHAT_MODEL,
        instructions="너는 한빛스포츠센터 상담원이다. 아래 참고자료만 근거로 한국어로 짧게 답한다. "
                     "참고자료끼리 내용이 다르면 그 사실을 그대로 말한다.",
        input=f"참고자료:\n{context}\n\n질문: {question}",
    )
    return resp.output_text


with tab_search:
    st.markdown("같은 질문을 **세 가지 방법**으로 검색해서 챗봇 답변을 비교합니다. 아래 질문 중 하나를 눌러보세요.")
    for c, s in zip(st.columns(len(SCENARIOS)), SCENARIOS):
        with c, st.container(border=True):
            st.markdown(f"**{s['q']}**")
            st.caption(s["point"])
            st.button("이 질문 해보기", key=f"run_{s['q']}", on_click=run_scenario, args=(s["q"],),
                      use_container_width=True)

    question = st.text_input("또는 직접 질문하기", key="q", placeholder="예: 수영 1개월 얼마야?")
    today = dt.date.today()

    if question:
        expect = EXPECT.get(question)
        if expect:
            st.markdown(f"🎯 정답: **{expect}**")

        extracted = extract_filter(question, today.isoformat())
        try:
            llm_day = dt.date.fromisoformat(extracted["date"]) if extracted["date"] else today
        except ValueError:
            llm_day = today
        found = (f"질문에서 **{llm_day}** 를 찾아서 그날 적용되는 요금표만 봅니다."
                 if extracted["date"] else "질문에 날짜가 없어서 **오늘** 기준 요금표만 봅니다.")

        modes = [
            ("🚫 메타데이터 안 씀", "필터 없음",
             "메타데이터를 무시하고, 질문과 비슷한 청크를 모두 찾아옵니다.", None),
            ("📌 항상 오늘 기준", "고정 필터",
             f"앱이 늘 **오늘({today})** 기준 요금표만 보도록 정해둡니다.", today),
            ("🤖 질문 보고 판단", "LLM이 필터 생성 (셀프 쿼리)",
             f"AI가 질문을 먼저 읽고 날짜를 찾습니다. {found}", llm_day),
        ]

        for box, (title, tech_name, how, day) in zip(st.columns(3), modes):
            with box, st.container(border=True):
                st.subheader(title)
                st.caption(tech_name)
                st.markdown(how)

                where, version = (None, None) if day is None else date_where(day)
                if day is not None and version is None:
                    st.warning(f"{day}에 적용되는 요금표가 없습니다. (요금표는 2026-01-01부터 있어요)")
                    continue
                hits = search(col, question, k, where)

                # 1) 챗봇 답변
                with st.spinner("답변 만드는 중…"):
                    text = answer(question, tuple(h["document"] for h in hits))
                st.markdown("💬 **챗봇 답변**")
                st.success(text)
                # 메타데이터를 안 쓰면 LLM이 어느 값을 고를지 매번 달라서 채점하지 않고, 아래 '섞임' 표시로 본다.
                if expect and day is not None:
                    st.markdown("✅ 정답이에요" if is_correct(text, expect) else f"❌ 틀렸어요 (정답: {expect})")

                # 2) 어떤 요금표를 봤는지
                seen = sorted({h["metadata"]["effective_from"] for h in hits})
                if len(seen) > 1:
                    st.warning("⚠️ 1월·9월 요금표를 **섞어서** 봤어요")
                else:
                    st.info(f"📄 **{version_label(seen[0])}** 만 봤어요")

                # 3) 찾아온 청크
                with st.expander(f"찾아온 청크 {len(hits)}개 보기"):
                    for h in hits:
                        m = h["metadata"]
                        st.markdown(f"- {h['document']}  \n  `{version_label(m['effective_from'])}`")
