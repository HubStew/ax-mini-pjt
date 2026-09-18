"""운동·영양 가이드라인 문서를 검색하는 RAG 파이프라인.

data/training_guidelines.md, data/nutrition_guidelines.md를 마크다운 섹션
기준으로 나눠 Chroma에 저장하고, retrieve_guideline(query)로 검색한다.
근거를 찾지 못하면 지어내지 않고 정직하게 안내한다 (SERVICE.md §4 환각 방지).
"""
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from langchain_aws import BedrockEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import MarkdownHeaderTextSplitter

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = str(BASE_DIR / "chroma_db")
COLLECTION_NAME = "health_agent_guidelines"

SOURCE_FILES = {
    "training_guidelines": DATA_DIR / "training_guidelines.md",
    "nutrition_guidelines": DATA_DIR / "nutrition_guidelines.md",
}

HEADERS_TO_SPLIT_ON = [("##", "section"), ("###", "subsection")]


def _load_and_split_documents():
    """두 가이드라인 문서를 ##/### 단위로 나누고 출처를 메타데이터에 남긴다.

    ## 단독으로만 나누면(예: 2. 단백질 섭취 기준) 그 안의 여러 ### 하위 주제
    (탄수화물·지방 배분, 과식 기준, 타이밍, 식품 함량 등)가 한 청크로 뭉쳐져
    임베딩이 여러 주제의 "평균"이 되고 검색 정확도가 떨어진다. ###까지 나눠
    각 하위 주제가 독립적으로 검색되게 한다.
    """
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=HEADERS_TO_SPLIT_ON)
    documents = []
    for source, path in SOURCE_FILES.items():
        text = path.read_text(encoding="utf-8")
        chunks = splitter.split_text(text)
        for chunk in chunks:
            chunk.metadata["source"] = source
        documents.extend(chunks)
    return documents


def _build_or_load_vectorstore(embeddings):
    """가이드라인 문서를 매번 새로 임베딩해 컬렉션을 채운다.

    문서량이 작아(수십 chunk) 매번 재구축해도 몇 초 안에 끝난다. 개수만 비교하는
    캐싱은 "## 섹션 개수는 그대로인데 내용만 바뀐" 경우를 못 잡아내는 문제가 있어
    (예: 기존 섹션 안에 ### 하위 항목만 추가된 경우) 단순하고 안전한 방식을 택한다.
    """
    documents = _load_and_split_documents()
    vectorstore = Chroma(
        persist_directory=CHROMA_DIR,
        embedding_function=embeddings,
        collection_name=COLLECTION_NAME,
        # 코사인 거리로 지정해야 관련성 점수가 0~1 범위로 정상 계산된다
        # (기본 L2 거리는 범위를 벗어나 경고가 발생하고 임계값 해석도 애매해진다)
        collection_metadata={"hnsw:space": "cosine"},
    )
    existing = vectorstore.get()
    if existing.get("ids"):
        vectorstore.delete(ids=existing["ids"])
    vectorstore.add_documents(documents)
    return vectorstore


# 쿼리 확장(query expansion)용 동의어 사전 — 임베딩 모델이 표기가 다른 동의어를
# (예: 영문 "Zone 2" vs 한글 축약 "존2"/"2존") 잘 매칭하지 못할 때, 검색 전에
# 정식 표현을 덧붙여 매칭 확률을 높인다. 늘어날 걸 감안해 데이터는 별도 파일로 분리
SYNONYM_MAP = json.loads((DATA_DIR / "query_synonyms.json").read_text(encoding="utf-8"))


_ZONE_PATTERN = re.compile(r"(?:존|zone)\s*([1-5])", re.IGNORECASE)


def _expand_query(query: str) -> str:
    """질의에 동의어 사전의 정식 표현을 덧붙여 검색 매칭률을 높인다.

    사전은 "존2"처럼 붙여 쓴 표현만 문자열 그대로 잡는데, 모델이 검색어를
    "존 2단계"처럼 띄어서 재구성하면 사전에 안 걸려 검색이 실패하는 게
    실제로 관측됐다. 존 표현만은 정규식으로 띄어쓰기를 허용해 더 안정적으로
    잡는다 (전역 임계값을 낮추는 대신 이 범위만 넓힘 - 다른 질문의 환각
    방지 기준에는 영향 없음).
    """
    extra_terms = [canonical for alias, canonical in SYNONYM_MAP.items() if alias in query]
    zone_match = _ZONE_PATTERN.search(query)
    if zone_match:
        extra_terms.append(f"Zone {zone_match.group(1)}")
    if not extra_terms:
        return query
    return query + " " + " ".join(extra_terms)


_embeddings = BedrockEmbeddings(
    model_id="amazon.titan-embed-text-v2:0",
    region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
)
_vectorstore = _build_or_load_vectorstore(_embeddings)

# k=3 유사도 검색은 관련 없는 질문에도 "가장 덜 무관한" 문서를 항상 반환하므로,
# 관련성 점수(코사인 유사도, 0~1)가 낮은 결과는 버려서 "근거 없음"을 실제로 판별한다.
# 문서 내 질의(0.2~0.66)와 무관한 질의(0.1~0.16)를 실측해 그 사이인 0.2로 설정
_RELEVANCE_THRESHOLD = 0.2


def retrieve_guideline(query: str) -> str:
    """운동·영양 가이드라인 문서에서 질의와 관련된 원칙을 검색해 반환한다."""
    expanded_query = _expand_query(query)
    scored_docs = _vectorstore.similarity_search_with_relevance_scores(expanded_query, k=3)
    relevant = [doc for doc, score in scored_docs if score > _RELEVANCE_THRESHOLD]
    if not relevant:
        return "관련 원칙을 찾지 못했습니다."
    def _label(d):
        parts = [d.metadata.get("source", "알 수 없음"), d.metadata.get("section", "")]
        if d.metadata.get("subsection"):
            parts.append(d.metadata["subsection"])
        return " · ".join(p for p in parts if p)

    return "\n\n".join(
        f"[출처: {_label(d)}]\n{d.page_content}"
        for d in relevant
    )


if __name__ == "__main__":
    tests = [
        "존2운동을 하면 뭐가 좋아?",
        "벌킹할 때 단백질 얼마나 먹어야 해?",
        "타이레놀 얼마나 먹어도 돼?",
    ]
    for q in tests:
        print(f"질문: {q}")
        print(retrieve_guideline(q))
        print("---")
