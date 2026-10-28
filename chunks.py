"""이용요금표 두 버전을 청크 + 메타데이터로 정리한 데이터.

표는 행 단위로 청크한다. 청크 본문에는 '몇 월 기준'인지가 들어 있지 않아서
두 버전을 구분할 수 있는 건 메타데이터뿐이다.
메타데이터는 source(출처)와 effective_from(시행일) 두 개만 둔다. 새 버전은 추가만 하면 되고
기존 청크를 고칠 필요가 없다. Chroma 범위 필터($lte 등)는 숫자에만 걸리므로 날짜는 YYYYMMDD 정수로 저장한다.
"""

VERSIONS = [
    {"version": 1, "source": "이용요금표.pdf", "effective_from": 20260101},
    {"version": 2, "source": "이용요금표_개정.pdf", "effective_from": 20260901},
]

INTRO = (
    "한빛스포츠센터 회원권은 종목과 기간을 선택해 등록한다. 기간은 1개월, 3개월, 6개월, 12개월 중 "
    "고를 수 있으며, 기간이 길수록 한 달 기준 요금이 낮아진다. 회원권은 등록일부터 시작하며 사용 "
    "시작일을 미룰 수 없다. 아래 모든 요금은 부가세를 포함한 금액이다."
)

DISCOUNT = (
    "두 종목 이상을 함께 등록하면 합산 금액의 10%를 할인한다. 만 65세 이상 회원과 장애인 등록 "
    "회원은 회원권 요금의 20%를 할인하며, 두 할인은 중복해서 적용하지 않는다. 같은 주소의 가족 "
    "회원은 두 번째 사람부터 5%를 할인한다. 할인은 등록 시점에만 적용하고 나중에 소급하지 않는다."
)

REVISION_POLICY = (
    "회원권 요금은 시설 운영 상황에 따라 바뀔 수 있으며, 바뀌는 경우 시행일 한 달 전에 게시판과 "
    "홈페이지에 공지한다. 개정 전에 등록한 회원권은 만료일까지 등록 당시 요금이 유지된다."
)

# 종목: (1개월, 3개월, 6개월, 12개월) — 버전별. None은 해당 기간 없음.
MEMBERSHIP = {
    "수영": ("수영 (자유수영)", {1: (78000, 210000, 390000, 720000), 2: (85000, 210000, 390000, 720000)}),
    "헬스": ("헬스", {1: (55000, 150000, 280000, 520000), 2: (59000, 150000, 280000, 520000)}),
    "수영+헬스": ("수영 + 헬스", {v: (110000, 300000, 560000, 1020000) for v in (1, 2)}),
    "필라테스": ("필라테스 (주 2회)", {v: (120000, 330000, 620000, None) for v in (1, 2)}),
    "요가": ("요가 (주 2회)", {v: (90000, 250000, 470000, None) for v in (1, 2)}),
    "스피닝": ("스피닝 (주 3회)", {v: (85000, 230000, 430000, None) for v in (1, 2)}),
}

# 항목: (요금, 비고) — 버전별
FACILITY = {
    "락커": {v: ("개인 락커", "월 8,000원", "3개월 24,000원 · 열쇠 분실 시 15,000원") for v in (1, 2)},
    "수건": {v: ("수건 대여", "월 5,000원", "1일 1매") for v in (1, 2)},
    "주차": {
        1: ("주차", "시간당 1,000원", "회원 무료 주차 없음"),
        2: ("주차", "시간당 1,000원", "1일 2시간까지 무료 · 초과분 시간당 1,000원"),
    },
    "일일권": {v: ("일일 이용권", "수영 9,000원 · 헬스 7,000원", "당일 1회") for v in (1, 2)},
}


def _won(n):
    return "없음" if n is None else f"{n:,}원"


def build_chunks():
    """Chroma add()에 넣을 ids, documents, metadatas를 만든다."""
    ids, documents, metadatas = [], [], []

    def add(v, key, text):
        ids.append(f"fee_v{v['version']}_{key}")
        documents.append(text)
        metadatas.append({"source": v["source"], "effective_from": v["effective_from"]})

    for v in VERSIONS:
        n = v["version"]
        add(v, "intro", INTRO)
        for key, (label, prices) in MEMBERSHIP.items():
            m1, m3, m6, m12 = prices[n]
            add(v, f"member_{key}", f"[회원권 요금] {label}: 1개월 {_won(m1)}, 3개월 {_won(m3)}, "
                                    f"6개월 {_won(m6)}, 12개월 {_won(m12)}")
        for key, rows in FACILITY.items():
            label, fee, note = rows[n]
            add(v, f"facility_{key}", f"[부대시설 요금] {label}: {fee} ({note})")
        add(v, "discount", DISCOUNT)
        add(v, "revision", REVISION_POLICY)

    return ids, documents, metadatas
