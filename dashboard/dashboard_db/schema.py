"""
대시보드 자체 DB(dashboard.db) 연결 및 스키마 마이그레이션.

기존 casino_news_watch/database.py, email_monitor/database.py와 동일한 패턴을
따른다: CREATE TABLE IF NOT EXISTS + ALTER TABLE ADD COLUMN(멱등)으로 안전하게
반복 실행 가능한 마이그레이션. 뉴스/이메일 프로그램의 DB는 이 모듈에서 전혀
다루지 않는다(읽기 전용 접근은 services/news_reader.py 참고).
"""

import sqlite3
from datetime import datetime, timezone

import config
from dashboard_db.glossary_operations_terms import CASINO_GLOSSARY_OPERATIONS_TERMS


# 새 비파괴 마이그레이션을 추가할 때 반드시 증가시킨다. SQLite 자체 메타데이터라
# 요청마다 수십 개 PRAGMA table_info를 반복하지 않고도 최신 여부를 한 번에 확인한다.
SCHEMA_VERSION = 2026080411

CASINO_GLOSSARY_SEED_TERMS = (
    ("game", "바카라", "Baccarat", "플레이어와 뱅커 중 어느 쪽의 카드 합이 9에 더 가까운지 맞히는 테이블 게임.", "두 편 중 9에 더 가까운 쪽을 고르는 게임입니다."),
    ("game", "플레이어", "Player", "바카라에서 두 베팅 영역 중 하나. 실제 게임 참가자를 뜻하는 것은 아님.", "사람이 아니라 바카라의 한쪽 팀 이름입니다."),
    ("game", "뱅커", "Banker", "바카라에서 두 베팅 영역 중 하나. 규칙상 일반적으로 하우스 엣지가 더 낮음.", "바카라의 다른 한쪽 팀 이름이며, 보통 승리 확률이 조금 높습니다."),
    ("game", "타이", "Tie", "바카라에서 플레이어와 뱅커의 점수가 같은 결과.", "양쪽 점수가 같아 무승부가 된 경우입니다."),
    ("game", "커미션", "Commission", "특정 게임의 당첨금에서 카지노가 규칙에 따라 공제하는 금액.", "승리금에서 카지노가 정해진 비율만큼 떼는 수수료입니다."),
    ("game", "사이드 베팅", "Side Bet", "기본 승패와 별개의 특정 조건에 거는 추가 베팅.", "본게임 외에 특정 카드 조합 등을 맞히는 추가 베팅입니다."),
    ("game", "테이블 게임", "Table Game", "딜러가 테이블에서 카드·주사위·룰렛 등을 진행하는 게임.", "딜러와 손님이 테이블에서 하는 카지노 게임입니다."),
    ("game", "슬롯머신", "Slot Machine", "랜덤 결과에 따라 심볼 조합의 당첨금을 지급하는 전자 게임기기.", "버튼을 눌러 같은 무늬가 맞으면 당첨금을 받는 기계입니다."),
    ("game", "하우스 엣지", "House Edge", "게임 규칙상 카지노가 장기적으로 가지는 통계적 우위.", "많은 게임을 반복했을 때 카지노 쪽에 남도록 설계된 평균 비율입니다."),
    ("game", "칩", "Chip", "카지노 게임 테이블에서 현금 대신 사용하는 가치 표시 토큰.", "카지노 안에서 돈처럼 사용하는 색깔 있는 토큰입니다."),
    ("business", "드롭액", "Drop", "카지노 고객이 게임을 위해 칩으로 교환한 총액 또는 테이블에 투입된 총 베팅 기준액.", "손님이 게임을 하려고 바꾼 돈의 총액으로, 매출은 아닙니다."),
    ("business", "홀드율", "Hold Rate", "카지노 승리금을 드롭액으로 나눈 비율. 단기적으로 변동성이 클 수 있음.", "손님이 바꾼 돈 중 결과적으로 카지노에 남은 비율입니다."),
    ("business", "총게임매출", "GGR", "총 베팅액에서 고객에게 지급한 당첨금을 뺀 금액(Gross Gaming Revenue).", "고객에게 돌려준 당첨금을 빼고 카지노에 남은 게임 매출입니다."),
    ("business", "콤프", "Comp", "고객의 게임 실적에 따라 제공하는 숙박·식음·교통 등의 무상 혜택.", "많이 이용한 고객에게 호텔방이나 식사 등을 서비스로 제공하는 것입니다."),
    ("business", "롤링", "Rolling", "VIP 카지노에서 칩 구매·사용 실적을 기준으로 계산하는 거래 및 정산 방식.", "VIP 고객이 얼마나 많은 칩을 사용했는지 누적해 관리하는 방식입니다."),
    ("business", "외국인 전용 카지노", "Foreigners-only Casino", "대한민국에서 외국인의 출입만 허용되는 카지노.", "한국인은 이용할 수 없고 외국인 관광객만 이용하는 카지노입니다."),
    ("business", "복합리조트", "Integrated Resort", "카지노와 호텔·MICE·쇼핑·공연·식음 시설 등을 하나의 단지에 결합한 대형 리조트.", "카지노뿐 아니라 잠자리·먹거리·쇼핑·공연을 한곳에서 이용하는 복합 시설입니다."),
    ("business", "관광진흥개발기금", "Tourism Promotion and Development Fund", "관광산업 진흥을 위해 카지노사업자 등에게 부과하거나 조성하는 법정 기금.", "카지노 매출 등을 기준으로 내고, 관광산업에 사용하는 기금입니다."),
    ("business", "VIP", "VIP", "고액 베팅과 높은 방문 가치를 보이는 주요 카지노 고객군.", "일반 고객보다 큰 금액으로 게임하는 핵심 고객입니다."),
    ("business", "매스", "Mass", "정킷 및 중소액 중심의 일반 카지노 고객군.", "VIP가 아닌 대부분의 일반 고객을 말합니다."),
    ("business", "프리미엄 매스", "Premium Mass", "일반 고객군 중 베팅 규모와 소비력이 상대적으로 높은 고객군.", "VIP 전용 관리는 받지 않지만 일반 고객보다 큰 금액을 쓰는 고객입니다."),
    ("business", "OCC", "Occupancy Rate", "호텔의 판매 가능 객실 중 실제 판매된 객실의 비율.", "오늘 팔 수 있는 방 중 몇 퍼센트가 찼는지 보여주는 수치입니다."),
    ("business", "ADR", "Average Daily Rate", "판매된 객실 1실당 평균 숙박 단가.", "손님이 팔린 방 하나에 평균적으로 얼마를 냈는지 보여줍니다."),
    ("business", "RevPAR", "Revenue per Available Room", "판매 가능 객실 1실당 매출. OCC와 ADR을 함께 반영함.", "빈방까지 포함해 호텔 방 하나가 평균적으로 얼마를 벌었는지 보여줍니다."),
    ("business", "EBITDA", "EBITDA", "이자·법인세·감가상각비 차감 전 이익.", "대출이자·세금·시설 감가상각을 빼기 전의 본업 수익력을 보는 지표입니다."),
    ("business", "CAPEX", "Capital Expenditure", "시설·장비·건물 등 장기 자산을 취득하거나 개선하는 자본적 지출.", "리조트나 카지노 시설을 짓고 고치는 데 쓰는 큰 투자금입니다."),
    ("business", "AML", "Anti-Money Laundering", "불법 자금의 세탁을 방지·탐지·보고하는 정책과 절차.", "불법으로 만든 돈이 카지노를 통해 정상적인 돈처럼 바뀌는 것을 막는 절차입니다."),
    ("business", "KYC", "Know Your Customer", "고객의 신원과 거래 목적, 위험 정보 등을 확인하는 절차.", "고객이 누구인지 확인하고 의심스러운 거래를 살피는 본인 확인 절차입니다."),
)

# Public glossary expansion supplied by the operator. Existing Korean terms are
# intentionally retained by the INSERT OR IGNORE migration below.
CASINO_GLOSSARY_SEED_TERMS += (
    ("business", "카지노", "Casino", "게임 시설과 관련 부대시설을 운영하는 사업장.", "돈을 걸고 게임하는 곳입니다."),
    ("game", "게이밍", "Gaming", "카지노에서 제공되는 사행성 게임 활동.", "카지노 게임 전반입니다."),
    ("game", "테이블 게임", "Table Game", "딜러가 진행하는 테이블형 게임.", "바카라·블랙잭 같은 게임입니다."),
    ("game", "전자 테이블 게임", "Electronic Table Game", "전자기기를 이용해 진행하는 테이블 게임.", "기계로 하는 바카라·룰렛입니다."),
    ("game", "슬롯머신", "Slot Machine", "릴 또는 화면 조합으로 당첨 여부를 결정하는 게임기.", "버튼을 눌러 당첨을 노리는 기계입니다."),
    ("game", "라이브 카지노", "Live Casino", "실제 딜러가 게임을 진행하는 카지노 영역.", "사람이 직접 진행하는 게임장입니다."),
    ("business", "매스", "Mass", "일반 고객을 대상으로 하는 영업 부문.", "일반 고객 시장입니다."),
    ("business", "프리미엄 매스", "Premium Mass", "일반 고객 중 상대적으로 베팅 규모가 큰 고객군.", "VIP 바로 아래 우량 고객입니다."),
    ("business", "VIP", "VIP", "고액 베팅 고객 또는 이를 대상으로 한 영업 부문.", "큰돈을 쓰는 핵심 고객입니다."),
    ("business", "하이 롤러", "High Roller", "매우 큰 금액을 베팅하는 고객.", "초고액 베팅 고객입니다."),
    ("business", "웨일", "Whale", "업계에서 최상위 수준의 초고액 고객을 지칭하는 표현.", "카지노에서 가장 큰손인 고객입니다."),
    ("business", "플레이어(고객)", "Player", "카지노 게임에 참여하는 고객.", "게임하는 손님입니다."),
    ("business", "이용 고객", "Patron", "카지노를 이용하는 고객을 포괄적으로 지칭하는 표현.", "카지노 방문 고객입니다."),
    ("business", "회원", "Member", "카지노 멤버십에 가입한 고객.", "회원 고객입니다."),
    ("business", "활성 회원", "Active Member", "일정 기간 내 방문 또는 게임 실적이 있는 회원.", "최근 실제로 이용한 회원입니다."),
    ("business", "신규 회원", "New Member", "처음 가입한 회원.", "신규 회원입니다."),
    ("business", "재방문", "Revisit", "기존 고객이 카지노를 다시 방문하는 것.", "다시 방문하는 것입니다."),
    ("business", "리텐션", "Retention", "고객이 지속적으로 재방문하도록 유지하는 정도.", "단골 고객을 붙잡는 힘입니다."),
    ("business", "고객 이탈", "Churn", "고객이 장기간 방문하지 않거나 이탈하는 현상.", "고객이 떠나는 것입니다."),
    ("business", "플레이어 개발", "Player Development", "우량 고객을 발굴하고 방문을 유도하는 영업 활동.", "큰손 고객 관리 영업입니다."),
    ("business", "카지노 호스트", "Casino Host", "주요 고객을 관리하고 방문·예약·편의를 지원하는 직원.", "VIP 전담 매니저입니다."),
    ("business", "정킷", "Junket", "고액 고객을 모집해 카지노 방문과 게임을 주선하는 사업자.", "VIP 손님을 데려오는 중개업체입니다."),
    ("business", "정킷 운영사", "Junket Operator", "정킷 사업을 운영하는 사업자.", "VIP 모집 대행사입니다."),
    ("business", "에이전트", "Agent", "고객 모집, 소개, 방문 유치 등을 담당하는 개인 또는 업체.", "손님을 소개하는 영업 파트너입니다."),
    ("business", "다이렉트 VIP", "Direct VIP", "정킷이나 대행사를 거치지 않고 카지노가 직접 관리하는 VIP.", "카지노가 직접 관리하는 큰손입니다."),
    ("business", "롤링 프로그램", "Rolling Program", "VIP 고객의 베팅 실적을 기준으로 수수료나 혜택을 제공하는 방식.", "베팅액에 따라 보상을 주는 제도입니다."),
    ("business", "롤링 칩", "Rolling Chip", "VIP 프로그램에서 베팅 실적을 집계하기 위해 사용하는 칩.", "베팅 실적을 세는 전용 칩입니다."),
    ("business", "롤링 금액", "Rolling Amount", "롤링칩이 반복적으로 베팅된 누적 금액.", "VIP 고객의 총 베팅 실적입니다."),
    ("business", "롤링 커미션", "Rolling Commission", "롤링 금액을 기준으로 지급하는 수수료.", "베팅액에 따라 주는 소개 수수료입니다."),
    ("business", "턴오버", "Turnover", "일정 기간 동안 고객이 베팅한 총금액.", "총 베팅액입니다."),
    ("business", "드롭액", "Drop", "고객이 현금이나 외화를 칩으로 교환한 금액.", "고객이 카지노에 가져온 게임 자금입니다."),
    ("business", "바이인", "Buy-in", "고객이 게임 참여를 위해 현금 등을 칩으로 바꾸는 행위 또는 금액.", "칩을 처음 사는 것입니다."),
    ("business", "캐시아웃", "Cash-out", "고객이 보유한 칩이나 크레딧을 현금으로 바꾸는 것.", "칩을 돈으로 바꾸는 것입니다."),
    ("business", "핸들", "Handle", "게임에 실제로 투입된 총 베팅 금액.", "게임판에 걸린 돈의 총합입니다."),
    ("business", "카지노 승리액", "Win", "카지노가 고객으로부터 획득한 순게임수익.", "카지노가 게임으로 번 돈입니다."),
    ("business", "고객 손실액", "Loss", "고객 관점에서 게임으로 잃은 금액.", "고객이 잃은 돈입니다."),
    ("business", "총게임매출", "Gross Gaming Revenue", "고객 베팅액에서 고객에게 지급한 당첨금을 차감한 금액.", "카지노 게임 총매출입니다."),
    ("business", "GGR", "GGR", "Gross Gaming Revenue의 약어.", "카지노 게임 총매출의 줄임말입니다."),
    ("business", "순게임매출", "Net Gaming Revenue", "GGR에서 일부 세금, 수수료, 프로모션 비용 등을 차감한 금액.", "실제로 남는 게임매출입니다."),
    ("business", "NGR", "NGR", "Net Gaming Revenue의 약어.", "순게임매출의 줄임말입니다."),
    ("business", "홀드", "Hold", "고객이 투입한 금액 중 카지노에 남은 비율 또는 금액.", "고객 돈 중 카지노가 가져간 몫입니다."),
    ("business", "홀드율", "Hold Percentage", "Drop 또는 Turnover 대비 Win의 비율.", "고객 자금 중 카지노가 번 비율입니다."),
    ("business", "이론적 승리액", "Theoretical Win", "게임 확률과 베팅 실적을 바탕으로 계산한 기대 수익.", "정상 확률대로라면 벌었어야 할 돈입니다."),
    ("business", "실제 승리액", "Actual Win", "실제 게임 결과에 따라 카지노가 얻은 수익.", "실제로 번 돈입니다."),
    ("business", "테오", "Theo", "Theoretical Win의 약칭.", "고객의 기대수익입니다."),
    ("game", "하우스 엣지", "House Edge", "게임 규칙상 카지노가 장기적으로 가지는 확률적 우위.", "시간이 길수록 카지노가 유리한 비율입니다."),
    ("game", "기대값", "Expected Value", "확률적으로 예상되는 평균 수익 또는 손실.", "장기적으로 기대되는 결과입니다."),
    ("game", "변동성", "Volatility", "게임 결과의 변동 폭.", "따고 잃는 폭이 얼마나 큰지 나타냅니다."),
    ("game", "분산", "Variance", "실제 결과가 기대값과 달라지는 정도.", "운에 따라 결과가 흔들리는 정도입니다."),
    ("game", "운 요인", "Luck Factor", "단기적으로 게임 실적에 영향을 미치는 운의 요소.", "그날 운이 좋았는지 나빴는지를 뜻합니다."),
    ("business", "카지노 승률", "Win Rate", "일정 기준 대비 카지노 수익 비율.", "카지노가 얼마나 벌었는지 보여주는 비율입니다."),
    ("business", "평균 베팅액", "Average Bet", "고객이 한 번에 베팅하는 평균 금액.", "판당 평균 베팅액입니다."),
    ("game", "베팅", "Bet", "게임 결과에 걸어 놓는 금액.", "판에 거는 돈입니다."),
    ("game", "웨이저", "Wager", "Bet과 유사하게 게임에 돈을 거는 행위 또는 금액.", "베팅을 뜻합니다."),
    ("game", "최소 베팅액", "Minimum Bet", "게임에 참여하기 위해 필요한 최소 베팅 금액.", "최소로 걸어야 하는 돈입니다."),
    ("game", "최대 베팅액", "Maximum Bet", "한 번에 베팅할 수 있는 최대 금액.", "한 판에 걸 수 있는 최고 금액입니다."),
    ("game", "게임 속도", "Game Pace", "일정 시간 동안 진행되는 게임 횟수.", "게임 진행 속도입니다."),
    ("game", "시간당 게임 수", "Hands per Hour", "한 시간 동안 진행된 게임 판수.", "시간당 게임 횟수입니다."),
    ("game", "게임 시간", "Gaming Time", "고객이 실제 게임에 참여한 시간.", "게임한 시간입니다."),
    ("business", "플레이어 레이팅", "Player Rating", "고객의 베팅액, 게임시간, 게임종류 등을 기록하는 절차.", "고객이 얼마나 게임했는지 평가하는 것입니다."),
    ("business", "레이팅 카드", "Rating Card", "고객의 게임 실적을 기록하는 자료.", "고객 게임 기록표입니다."),
    ("business", "고객 추적 시스템", "Player Tracking System", "회원별 방문·베팅·게임 실적을 관리하는 시스템.", "고객 게임 이력 관리 시스템입니다."),
    ("business", "로열티 프로그램", "Loyalty Program", "이용 실적에 따라 등급과 혜택을 제공하는 제도.", "카지노 멤버십 보상제도입니다."),
    ("business", "회원 등급", "Tier", "고객의 이용 실적에 따라 구분한 회원 등급.", "멤버십 등급입니다."),
    ("business", "등급 포인트", "Tier Point", "회원 등급 산정에 사용되는 포인트.", "등급을 올리는 점수입니다."),
    ("business", "콤프", "Comp", "고객의 게임 실적에 따라 제공하는 무료 또는 할인 혜택.", "식사·객실 등을 무료로 주는 혜택입니다."),
    ("business", "무료 제공 혜택", "Complimentary", "Comp의 정식 표현.", "무료 제공 서비스입니다."),
    ("business", "콤프율", "Comp Rate", "고객의 이론적 수익 대비 제공 가능한 혜택 비율.", "고객 실적 중 혜택으로 돌려주는 비율입니다."),
    ("business", "콤프 달러", "Comp Dollar", "카지노 내에서 사용할 수 있도록 지급하는 보상성 포인트.", "카지노 전용 포인트입니다."),
    ("business", "프리 플레이", "Free Play", "현금 대신 게임에 사용할 수 있는 프로모션 크레딧.", "공짜로 게임할 수 있는 금액입니다."),
    ("business", "매치 플레이", "Match Play", "고객의 베팅 금액에 맞춰 카지노가 추가 베팅 혜택을 제공하는 쿠폰.", "고객 돈만큼 베팅을 보태주는 쿠폰입니다."),
    ("business", "리베이트", "Rebate", "일정 손실이나 베팅 실적에 따라 일부를 돌려주는 혜택.", "잃은 돈 일부를 환급해 주는 것입니다."),
    ("business", "손실 리베이트", "Loss Rebate", "고객 손실액을 기준으로 지급하는 환급.", "손실금 일부를 돌려주는 제도입니다."),
    ("business", "캐시백", "Cashback", "이용 실적에 따라 현금 또는 현금성 혜택을 지급하는 방식.", "이용 금액 일부를 돌려주는 것입니다."),
    ("business", "인센티브", "Incentive", "고객 방문이나 베팅을 유도하기 위해 제공하는 보상.", "방문을 끌어내는 혜택입니다."),
    ("business", "프로모션", "Promotion", "고객 유치와 이용 촉진을 위한 이벤트나 보상 활동.", "카지노 판촉행사입니다."),
    ("business", "캠페인", "Campaign", "특정 고객군과 목표를 대상으로 진행하는 마케팅 활동.", "목표가 정해진 고객 유치 활동입니다."),
    ("business", "오퍼", "Offer", "특정 고객에게 제안하는 객실·식음·게임 혜택.", "고객 맞춤 혜택입니다."),
    ("business", "혜택 교환", "Redemption", "포인트나 쿠폰을 혜택으로 교환하는 것.", "포인트를 실제 혜택으로 쓰는 것입니다."),
    ("business", "카지노 신용", "Casino Credit", "카지노가 일정 조건에 따라 고객에게 제공하는 게임용 신용.", "외상으로 제공하는 게임 자금입니다."),
    ("business", "마커", "Marker", "고객이 카지노로부터 신용을 제공받을 때 작성하는 지급 약정.", "카지노 외상 차용증입니다."),
    ("business", "프런트 머니", "Front Money", "고객이 게임 전 카지노에 미리 예치하는 자금.", "미리 맡겨 놓는 게임 돈입니다."),
    ("business", "예치금", "Deposit", "카지노 계좌나 카운터 등에 고객이 예치한 금액.", "맡겨 놓은 돈입니다."),
    ("business", "신용 한도", "Credit Line", "고객에게 승인된 카지노 신용 한도.", "외상으로 쓸 수 있는 최대 금액입니다."),
    ("business", "정산", "Settlement", "게임 종료 후 칩, 신용, 송금 등을 정산하는 절차.", "게임 돈을 최종 계산하는 것입니다."),
    ("business", "케이지", "Cage", "현금, 칩, 수표, 외환 등을 처리하는 카지노 계산 부서.", "카지노 환전·계산 창구입니다."),
)

# Management and finance glossary. These remain in the existing business
# category so older databases and public filters keep their stable contract.
CASINO_GLOSSARY_SEED_TERMS += (
    ("business", "총게임매출", "Gross Gaming Revenue, GGR", "고객의 게임 손실액을 기준으로 산정한 카지노의 총게임수익.", "카지노가 게임에서 번 총금액입니다."),
    ("business", "순게임매출", "Net Gaming Revenue, NGR", "GGR에서 리베이트, 수수료, 프로모션 등 차감 항목을 반영한 매출.", "각종 고객 비용을 빼고 남은 게임매출입니다."),
    ("business", "카지노 승액", "Casino Win", "일정 기간 카지노가 게임 결과로 획득한 금액.", "카지노가 실제 게임에서 딴 돈입니다."),
    ("business", "드롭액", "Drop", "고객이 현금·외화 등을 칩으로 교환하거나 테이블에 투입한 금액.", "고객이 게임하려고 가져온 돈입니다."),
    ("business", "테이블 드롭", "Table Drop", "테이블 게임에서 발생한 드롭액.", "테이블 게임에 들어온 고객 자금입니다."),
    ("business", "슬롯 코인인", "Slot Coin-in", "슬롯머신에 반복적으로 투입된 총 베팅액.", "슬롯에서 고객이 누적해서 건 돈입니다."),
    ("business", "총베팅액", "Turnover", "일정 기간 반복적으로 베팅된 누적 금액.", "모든 판의 베팅액을 더한 금액입니다."),
    ("business", "핸들", "Handle", "게임에 실제로 걸린 누적 베팅액.", "게임판에서 오간 총 베팅액입니다."),
    ("business", "홀드율", "Hold Percentage", "드롭액 대비 카지노 승액의 비율.", "고객이 가져온 돈 중 카지노가 번 비율입니다."),
    ("business", "승률", "Win Rate", "드롭액이나 베팅액 대비 카지노 승액의 비율.", "카지노 수익률입니다."),
    ("business", "이론승액", "Theoretical Win", "평균 베팅액, 게임시간, 게임속도, 하우스 엣지로 계산한 기대수익.", "정상 확률이라면 벌었어야 할 돈입니다."),
    ("business", "실제승액", "Actual Win", "실제 게임 결과로 발생한 카지노 승액.", "실제로 번 돈입니다."),
    ("business", "기대수익 차이", "Actual vs. Theoretical Variance", "실제승액과 이론승액의 차이.", "예상보다 더 벌었는지 덜 벌었는지 보여줍니다."),
    ("game", "하우스 엣지", "House Edge", "게임 규칙상 카지노가 갖는 장기적인 확률 우위.", "장기적으로 카지노에 유리한 비율입니다."),
    ("business", "게임매출총이익", "Gaming Margin", "게임매출에서 직접 변동비를 차감한 이익.", "게임매출에서 직접비를 뺀 이익입니다."),
    ("business", "매출총이익", "Gross Profit", "매출액에서 매출원가를 차감한 금액.", "상품·서비스를 팔고 1차로 남은 이익입니다."),
    ("business", "영업이익", "Operating Profit", "매출에서 영업 관련 비용을 차감한 이익.", "본업으로 벌어들인 이익입니다."),
    ("business", "상각전영업이익", "EBITDA", "이자·세금·감가상각비 차감 전 이익.", "사업 자체의 현금창출력을 보는 지표입니다."),
    ("business", "공헌이익", "Contribution Margin", "매출에서 변동비를 차감한 이익.", "고객이나 사업이 고정비 충당에 기여한 금액입니다."),
    ("business", "손익분기점", "Break-even Point, BEP", "총수익과 총비용이 같아지는 지점.", "이익도 손실도 없는 매출 수준입니다."),
    ("business", "고객획득비용", "Customer Acquisition Cost, CAC", "신규 고객 한 명을 유치하는 데 들어간 비용.", "고객 한 명 데려오는 데 든 돈입니다."),
    ("business", "고객생애가치", "Customer Lifetime Value, CLV·LTV", "고객이 거래 기간 전체에 걸쳐 기여할 것으로 예상되는 가치.", "한 고객이 장기간 가져다줄 총이익입니다."),
    ("business", "투자수익률", "Return on Investment, ROI", "투자금액 대비 발생한 이익의 비율.", "투자한 돈에 비해 얼마나 벌었는지 보여줍니다."),
    ("business", "광고수익률", "Return on Ad Spend, ROAS", "광고비 대비 발생한 매출.", "광고비 1원으로 얼마의 매출을 만들었는지 보여줍니다."),
    ("business", "객단가", "Average Revenue per Customer", "고객 한 명당 발생한 평균 매출.", "손님 한 명이 평균적으로 쓴 돈입니다."),
    ("business", "방문당 매출", "Revenue per Visit", "방문 1회당 발생한 평균 매출.", "한 번 방문할 때 발생한 평균 매출입니다."),
    ("business", "방문당 기대수익", "Theo per Trip", "고객의 방문 1회당 이론승액.", "고객이 한 번 올 때 기대되는 수익입니다."),
    ("business", "고객당 기대수익", "Theo per Player", "고객 1인당 이론적으로 기대되는 카지노 수익.", "손님 한 명에게 기대하는 수익입니다."),
    ("business", "게임일당 수익", "Win per Gaming Day", "고객이 게임한 하루당 발생한 카지노 승액.", "고객이 게임한 하루 기준 수익입니다."),
    ("business", "일평균 드롭", "Average Daily Drop, ADD", "하루 평균 발생한 드롭액.", "하루에 평균적으로 들어온 게임 자금입니다."),
    ("business", "일평균 이론승액", "Average Daily Theoretical, ADT", "고객의 게임일 하루당 평균 이론승액.", "고객 하루 이용 기준 예상수익입니다."),
    ("business", "일평균 승액", "Average Daily Win, ADW", "고객 게임일 하루당 평균 실제승액.", "고객 하루 이용 기준 실제수익입니다."),
    ("business", "게임인원", "Gaming Visitors", "실제 게임에 참여한 고객 수.", "단순 입장이 아니라 게임한 사람 수입니다."),
    ("business", "입장객", "Admissions", "카지노에 입장한 전체 고객 수.", "카지노에 들어온 사람 수입니다."),
    ("business", "전환율", "Conversion Rate", "입장객 중 회원가입·게임·구매 등 목표 행동을 한 비율.", "들어온 고객 중 실제 행동한 비율입니다."),
    ("business", "재방문율", "Revisit Rate", "일정 기간 내 다시 방문한 고객 비율.", "다시 찾아온 고객의 비율입니다."),
    ("business", "활성고객", "Active Player", "기준 기간 중 실제 게임 기록이 있는 고객.", "최근 게임한 고객입니다."),
    ("business", "휴면고객", "Dormant Player", "일정 기간 방문이나 게임이 없는 고객.", "한동안 오지 않은 고객입니다."),
    ("business", "이탈고객", "Churned Player", "장기간 방문하지 않아 이탈한 것으로 판단되는 고객.", "사실상 떠난 고객입니다."),
    ("business", "고객이탈률", "Churn Rate", "기존 고객 중 이탈한 고객의 비율.", "고객이 빠져나가는 비율입니다."),
)

# ETG terminology supplied by the operator. These rows are also updated during
# this migration so the two previously seeded terms receive the new wording
# without creating duplicates.
CASINO_GLOSSARY_ETG_TERMS = (
    ("game", "전자 테이블 게임", "Electronic Table Game, ETG", "전통적인 테이블 게임을 전자 단말기와 자동화 시스템으로 제공하는 게임 형태.", "딜러 대신 화면과 기계로 하는 바카라·룰렛·식보입니다."),
    ("business", "ETG 드롭", "ETG Drop", "고객이 ETG 게임을 이용하기 위해 투입한 자금.", "고객이 ETG 게임을 위해 투입한 자금입니다."),
    ("business", "ETG 턴오버", "ETG Turnover", "ETG에서 반복적으로 베팅된 금액을 누적한 총액.", "ETG에서 반복 베팅된 누적 금액입니다."),
    ("business", "ETG 승액", "ETG Win", "ETG 게임 결과로 카지노가 획득한 금액.", "ETG에서 카지노가 번 금액입니다."),
    ("business", "ETG 홀드율", "ETG Hold Percentage", "ETG 베팅액 대비 카지노 승액의 비율.", "ETG 베팅액 중 카지노에 남은 비율입니다."),
    ("business", "단말기당 승액", "Win per Terminal", "ETG 단말기 한 대당 발생한 평균 카지노 승액.", "ETG 기기 한 대가 벌어들인 금액입니다."),
    ("business", "단말기 가동률", "Terminal Utilization", "전체 ETG 단말기 또는 좌석 중 실제 게임에 이용된 비율.", "전체 ETG 좌석 중 실제 이용된 비율입니다."),
    ("business", "좌석 점유율", "Seat Occupancy", "운영 중인 ETG 좌석 가운데 고객이 실제 사용한 좌석의 비율.", "운영 좌석 중 고객이 사용한 비율입니다."),
    ("game", "시간당 게임 수", "Decisions per Hour", "한 시간 동안 완료된 게임의 횟수.", "한 시간 동안 진행된 게임 횟수입니다."),
)


def is_current(connection):
    row = connection.execute("PRAGMA user_version").fetchone()
    return bool(row and int(row[0]) == SCHEMA_VERSION)


def connect(db_path=None, *, run_migrations=True):
    """대시보드 DB에 연결한다.

    직접 호출하는 스크립트와 테스트의 기존 안전 동작을 위해 기본적으로
    마이그레이션을 실행한다. 웹 요청 경로는 ``extensions.dashboard_db``가
    프로세스별 최초 연결에서만 마이그레이션을 실행한다.
    """
    connection = sqlite3.connect(db_path or config.DASHBOARD_DB_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if run_migrations and not is_current(connection):
        migrate(connection)
    return connection


def _ensure_column(connection, table, column, coltype):
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def migrate(connection):
    """스키마를 최신 상태로 맞춘다. 기존 테이블/데이터는 절대 삭제하지 않는다."""

    # ---- dashboard_users ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login_at TEXT
        )
        """
    )
    # 기존 계정은 이 기능 도입 전부터 대시보드를 관리하던 계정이므로 admin으로 이관한다.
    _ensure_column(connection, "dashboard_users", "role", "TEXT NOT NULL DEFAULT 'admin'")
    _ensure_column(connection, "dashboard_users", "is_active", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(connection, "dashboard_users", "updated_at", "TEXT")
    _ensure_column(connection, "dashboard_users", "password_changed_at", "TEXT")
    _ensure_column(connection, "dashboard_users", "landing_page", "TEXT NOT NULL DEFAULT 'dashboard'")
    _ensure_column(connection, "dashboard_users", "email", "TEXT")
    _ensure_column(connection, "dashboard_users", "google_sub", "TEXT")
    _ensure_column(connection, "dashboard_users", "name", "TEXT")
    _ensure_column(connection, "dashboard_users", "picture_url", "TEXT")
    _ensure_column(connection, "dashboard_users", "deletion_requested_at", "TEXT")
    _ensure_column(connection, "dashboard_users", "deletion_scheduled_at", "TEXT")
    _ensure_column(connection, "dashboard_users", "deleted_at", "TEXT")
    _ensure_column(
        connection, "dashboard_users", "approval_status",
        "TEXT NOT NULL DEFAULT 'approved'",
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_dashboard_users_email_unique
        ON dashboard_users(LOWER(email))
        WHERE email IS NOT NULL AND TRIM(email) != ''
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_dashboard_users_google_sub_unique
        ON dashboard_users(google_sub)
        WHERE google_sub IS NOT NULL AND TRIM(google_sub) != ''
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dashboard_users_deletion_schedule
        ON dashboard_users(approval_status, deletion_scheduled_at)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_user_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_user_id INTEGER,
            target_username TEXT NOT NULL,
            action TEXT NOT NULL,
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL,
            detail_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_audit_created "
        "ON dashboard_user_audit(created_at DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_user_permissions (
            user_id INTEGER NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
            permission_code TEXT NOT NULL,
            allowed INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            updated_by INTEGER,
            PRIMARY KEY (user_id, permission_code)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS login_ip_security (
            ip_address TEXT PRIMARY KEY,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            first_failed_at TEXT,
            last_failed_at TEXT,
            blocked_at TEXT,
            blocked_by TEXT,
            unblocked_at TEXT,
            note TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS security_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            action TEXT NOT NULL,
            resource_type TEXT,
            resource_id TEXT,
            success INTEGER NOT NULL DEFAULT 1,
            detail_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_security_audit_created "
        "ON security_audit_log(created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_security_audit_anonymous_dedupe "
        "ON security_audit_log(username, ip_address, action, resource_type, "
        "resource_id, created_at DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_active_sessions (
            session_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
            username TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            absolute_expires_at TEXT NOT NULL,
            revoked_at TEXT,
            revoke_reason TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_active_sessions_user "
        "ON dashboard_active_sessions(user_id, revoked_at, last_seen_at DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS remember_login_tokens (
            selector TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL,
            user_id INTEGER NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked_at TEXT,
            user_agent TEXT,
            ip_address TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_remember_tokens_user "
        "ON remember_login_tokens(user_id, revoked_at, expires_at)"
    )

    # ---- action_items ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS action_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            source_type TEXT NOT NULL DEFAULT 'manual',
            source_ref_id TEXT,
            owner TEXT,
            created_at TEXT NOT NULL,
            due_date TEXT,
            due_date_confidence TEXT DEFAULT 'unclear',
            priority TEXT NOT NULL DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'not_started',
            ai_suggested INTEGER NOT NULL DEFAULT 0,
            approved_by_user INTEGER NOT NULL DEFAULT 1,
            ai_recommended_action TEXT,
            completed_at TEXT,
            memo TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_action_items_status ON action_items(status)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_action_items_due_date ON action_items(due_date)")
    _ensure_column(connection, "action_items", "reported_by", "TEXT")
    _ensure_column(connection, "action_items", "bug_page", "TEXT")
    _ensure_column(connection, "action_items", "environment", "TEXT")
    _ensure_column(connection, "action_items", "feedback_type", "TEXT NOT NULL DEFAULT '일반 의견'")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_action_items_report_rate "
        "ON action_items(source_type, reported_by, created_at DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS action_item_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_item_id INTEGER NOT NULL REFERENCES action_items(id) ON DELETE CASCADE,
            author_id INTEGER NOT NULL REFERENCES dashboard_users(id),
            content TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            deleted_by INTEGER REFERENCES dashboard_users(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_action_item_comments_item "
        "ON action_item_comments(action_item_id, is_deleted, created_at)"
    )

    # ---- community_posts ----
    # This table can already exist from an earlier partial rollout.  The
    # idempotent migration preserves every existing row.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS community_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id INTEGER NOT NULL REFERENCES dashboard_users(id),
            author_username TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_community_posts_created "
        "ON community_posts(created_at DESC, id DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_community_posts_author_created "
        "ON community_posts(author_id, created_at DESC)"
    )
    _ensure_column(connection, "community_posts", "image_url", "TEXT")
    _ensure_column(connection, "community_posts", "pdf_url", "TEXT")
    _ensure_column(
        connection, "community_posts", "is_deleted",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(connection, "community_posts", "deleted_at", "TEXT")
    _ensure_column(connection, "community_posts", "deleted_by", "INTEGER")
    _ensure_column(
        connection, "community_posts", "is_pinned",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(
        connection, "community_posts", "board_type",
        "TEXT NOT NULL DEFAULT 'community'",
    )
    connection.execute(
        "UPDATE community_posts SET board_type='community' "
        "WHERE board_type IS NULL OR TRIM(board_type)=''"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_community_posts_board_created "
        "ON community_posts(board_type, created_at DESC, id DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_community_posts_visible "
        "ON community_posts(is_deleted, board_type, created_at DESC, id DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_community_posts_board_pinned_created "
        "ON community_posts(is_deleted, board_type, is_pinned DESC, created_at DESC, id DESC)"
    )

    # ---- community_comments ----
    # Comments are soft-deleted so moderation does not destroy audit history.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS community_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
            author_id INTEGER NOT NULL REFERENCES dashboard_users(id),
            author_username TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            deleted_by INTEGER REFERENCES dashboard_users(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_community_comments_post_created "
        "ON community_comments(post_id, is_deleted, created_at, id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_community_comments_author_created "
        "ON community_comments(author_id, created_at DESC)"
    )

    # ---- community_post_recommendations ----
    # 한 계정은 한 게시글을 한 번만 추천할 수 있다.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS community_post_recommendations (
            post_id INTEGER NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            PRIMARY KEY (post_id, user_id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_community_recommendations_user "
        "ON community_post_recommendations(user_id, created_at DESC)"
    )

    # ---- executive_insights ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS executive_insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insight_date TEXT NOT NULL,
            title TEXT NOT NULL,
            importance TEXT NOT NULL DEFAULT 'medium',
            evidence_json TEXT,
            facts TEXT,
            ai_interpretation TEXT,
            expected_impact TEXT,
            recommended_action TEXT,
            needs_executive_review INTEGER NOT NULL DEFAULT 0,
            category TEXT NOT NULL DEFAULT 'estimate',
            prompt_version TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_executive_insights_date ON executive_insights(insight_date)"
    )

    # ---- performance_reports (텔레그램 실적 메시지 수집) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS performance_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT NOT NULL,
            telegram_update_id INTEGER,
            telegram_message_id INTEGER,
            telegram_chat_id TEXT,
            message_kind TEXT NOT NULL,
            header_type TEXT,
            raw_text TEXT,
            parsed_json TEXT,
            parsing_status TEXT NOT NULL DEFAULT 'ok',
            parsing_error TEXT,
            received_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_perf_reports_message "
        "ON performance_reports(telegram_chat_id, telegram_message_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_perf_reports_date ON performance_reports(report_date)"
    )

    # ---- tourism_visitor_stats (출입국관광통계 API 캐시) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tourism_visitor_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ym TEXT NOT NULL,
            nat_label TEXT NOT NULL,
            visitor_count INTEGER NOT NULL,
            fetched_at TEXT NOT NULL,
            UNIQUE(ym, nat_label)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tourism_visitor_stats_ym "
        "ON tourism_visitor_stats(ym)"
    )
    _ensure_column(connection, "tourism_visitor_stats", "changed_at", "TEXT")
    connection.execute(
        "UPDATE tourism_visitor_stats SET changed_at=fetched_at WHERE changed_at IS NULL"
    )

    # ---- dashboard_analysis_runs ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_analysis_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            prompt_version TEXT,
            input_hash TEXT,
            error_message TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_analysis_runs_type ON dashboard_analysis_runs(run_type, started_at)"
    )

    # ---- telegram_ingest_state (getUpdates 오프셋, 단일 행) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_ingest_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_update_id INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )

    # ---- monitored_companies (DART 관심기업) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS monitored_companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            dart_corp_code TEXT,
            aliases_json TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_monitored_companies_code "
        "ON monitored_companies(dart_corp_code)"
    )

    # ---- company_research_profiles (공식 자료 기반 기초 조사 베이스라인) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_research_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL UNIQUE,
            dart_corp_code TEXT,
            stock_code TEXT,
            legal_name TEXT,
            legal_name_eng TEXT,
            ceo_names TEXT,
            headquarters TEXT,
            established_date TEXT,
            fiscal_month TEXT,
            website_url TEXT,
            ir_url TEXT,
            business_summary TEXT,
            strategy_summary TEXT,
            key_assets_json TEXT,
            opportunities_json TEXT,
            risks_json TEXT,
            financials_json TEXT,
            sources_json TEXT,
            source_period TEXT,
            researched_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_research_code "
        "ON company_research_profiles(dart_corp_code)"
    )

    # ---- company_executive_profiles (회사별 복수 대표자 공개 프로필) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_executive_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            profile_as_of TEXT NOT NULL,
            executive_name TEXT NOT NULL,
            title TEXT NOT NULL,
            appointed_on TEXT,
            workplace_address TEXT,
            birth_date TEXT,
            high_school TEXT,
            university TEXT,
            major TEXT,
            source_label TEXT NOT NULL,
            imported_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_company_executive_profiles_unique
        ON company_executive_profiles(
            company_name, profile_as_of, executive_name, title
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_executive_profiles_latest "
        "ON company_executive_profiles(company_name, profile_as_of DESC, id)"
    )

    # ---- company_benefits (회사별 복리후생 및 종료 이력) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_benefits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '기타',
            benefit_name TEXT NOT NULL,
            support_value TEXT NOT NULL DEFAULT '',
            benefit_level TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            effective_from TEXT,
            ended_on TEXT,
            created_by INTEGER REFERENCES dashboard_users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(ended_on IS NULL OR effective_from IS NULL OR ended_on >= effective_from)
        )
        """
    )
    connection.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_company_benefits_active_unique
           ON company_benefits(company_name, benefit_name COLLATE NOCASE)
           WHERE ended_on IS NULL"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_company_benefits_list
           ON company_benefits(company_name, ended_on, category, benefit_name)"""
    )

    # ---- company_recruitment_guides (기업별 면접·실기 족보) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_recruitment_guides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            process_type TEXT NOT NULL,
            position_name TEXT NOT NULL DEFAULT '',
            stage_name TEXT NOT NULL DEFAULT '',
            question_text TEXT NOT NULL,
            atmosphere TEXT NOT NULL DEFAULT '',
            experience_period TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_by INTEGER REFERENCES dashboard_users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(process_type IN ('interview', 'practical', 'written', 'other')),
            CHECK(experience_period = '' OR experience_period GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]')
        )
        """
    )
    connection.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_recruitment_guides_unique
           ON company_recruitment_guides(
               company_name, process_type, experience_period,
               question_text COLLATE NOCASE
           )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_recruitment_guides_list
           ON company_recruitment_guides(
               company_name, experience_period DESC, process_type, id DESC
           )"""
    )

    # ---- company_content_comments (복리후생·채용 족보 댓글 및 대댓글) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_content_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            parent_id INTEGER REFERENCES company_content_comments(id),
            author_id INTEGER NOT NULL REFERENCES dashboard_users(id),
            author_username TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            deleted_by INTEGER REFERENCES dashboard_users(id),
            CHECK(target_type IN ('benefit', 'recruitment_guide')),
            CHECK(parent_id IS NULL OR parent_id <> id)
        )
        """
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_company_content_comments_target
           ON company_content_comments(
               target_type, target_id, parent_id, created_at, id
           )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_company_content_comments_author
           ON company_content_comments(author_id, created_at DESC)"""
    )

    # ---- company_financial_reports / values (VALUESearch 원본 재무제표) ----
    # 파일 메타데이터와 원 단위 계정값을 분리해 보관한다. 동일 파일을 다시
    # 반영해도 중복 보고서가 생기지 않으며 기존 회사 조사 JSON은 그대로 둔다.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_financial_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            legal_name TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_company_code TEXT,
            statement_type TEXT NOT NULL,
            accounting_standard TEXT,
            currency TEXT NOT NULL DEFAULT 'KRW',
            unit TEXT NOT NULL DEFAULT 'KRW',
            report_as_of TEXT,
            source_filename TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            UNIQUE(company_name, statement_type, source_sha256)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_financial_reports_lookup "
        "ON company_financial_reports(company_name, statement_type, report_as_of, imported_at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_financial_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL
                REFERENCES company_financial_reports(id) ON DELETE CASCADE,
            account_code TEXT NOT NULL,
            account_name TEXT NOT NULL,
            account_depth INTEGER NOT NULL DEFAULT 0,
            display_order INTEGER NOT NULL,
            fiscal_date TEXT NOT NULL,
            period_type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            UNIQUE(report_id, display_order, fiscal_date)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_financial_values_period "
        "ON company_financial_values(report_id, fiscal_date, account_depth, display_order)"
    )

    # ---- company_credit_ratings (회사별 신용평가 이력) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_credit_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            rating TEXT NOT NULL,
            evaluated_on TEXT NOT NULL,
            financial_as_of TEXT,
            rating_type TEXT NOT NULL,
            agency TEXT NOT NULL,
            source_label TEXT NOT NULL,
            imported_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_company_credit_ratings_unique
        ON company_credit_ratings(
            company_name, agency, evaluated_on, rating, rating_type,
            COALESCE(financial_as_of, '')
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_credit_ratings_latest "
        "ON company_credit_ratings(company_name, evaluated_on DESC, id DESC)"
    )

    # ---- research_documents (사용자 업로드 증권사·산업 리포트 자료실) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_type TEXT NOT NULL DEFAULT 'research',
            company_name TEXT NOT NULL,
            title TEXT NOT NULL,
            publisher TEXT,
            report_date TEXT,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL UNIQUE,
            mime_type TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            page_count INTEGER,
            extracted_text TEXT,
            extraction_status TEXT NOT NULL DEFAULT 'pending',
            ai_summary TEXT,
            investment_stance TEXT,
            target_price TEXT,
            key_points_json TEXT,
            risks_json TEXT,
            analyzed_at TEXT,
            error_message TEXT,
            uploaded_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(company_name, sha256)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_documents_company "
        "ON research_documents(company_name, report_date, created_at)"
    )
    _ensure_column(connection, "research_documents", "ai_suggested_title", "TEXT")
    _ensure_column(connection, "research_documents", "industry_impact", "TEXT")
    _ensure_column(
        connection,
        "research_documents",
        "document_type",
        "TEXT NOT NULL DEFAULT 'research'",
    )
    # 이전 운영 자료는 모두 리서치 자료다. NULL/빈 값만 보정해 기존 데이터를 보존한다.
    connection.execute(
        """
        UPDATE research_documents
        SET document_type = 'research'
        WHERE document_type IS NULL OR TRIM(document_type) = ''
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_documents_type_date "
        "ON research_documents(document_type, report_date, created_at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_document_companies (
            document_id INTEGER NOT NULL
                REFERENCES research_documents(id) ON DELETE CASCADE,
            company_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (document_id, company_name)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_document_companies_company "
        "ON research_document_companies(company_name, document_id)"
    )
    # 기존 단일 회사 자료도 새 다중 연결 구조에서 그대로 검색되도록 이관한다.
    connection.execute(
        """
        INSERT OR IGNORE INTO research_document_companies
            (document_id, company_name, created_at)
        SELECT id, company_name, created_at
        FROM research_documents
        WHERE company_name IS NOT NULL AND TRIM(company_name) != ''
        """
    )

    # ---- dart_disclosures ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dart_disclosures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rcept_no TEXT NOT NULL UNIQUE,
            corp_name TEXT,
            dart_corp_code TEXT,
            report_nm TEXT,
            pblntf_ty TEXT,
            rcept_dt TEXT,
            flr_nm TEXT,
            dart_link TEXT,
            is_important INTEGER NOT NULL DEFAULT 0,
            telegram_alert_sent_at TEXT,
            fetched_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_dart_disclosures_dt ON dart_disclosures(rcept_dt)")

    # ---- disclosure_analysis ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS disclosure_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            disclosure_id INTEGER NOT NULL REFERENCES dart_disclosures(id),
            ai_summary TEXT,
            importance TEXT,
            financial_impact TEXT,
            competitive_impact TEXT,
            risk_category TEXT,
            needs_executive_review INTEGER NOT NULL DEFAULT 0,
            prompt_version TEXT,
            analyzed_at TEXT,
            error_message TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_disclosure_analysis_disclosure "
        "ON disclosure_analysis(disclosure_id)"
    )

    # ---- monitored_laws ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS monitored_laws (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            law_name TEXT NOT NULL UNIQUE,
            law_id TEXT,
            mst TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    # ---- law_updates ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS law_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitored_law_id INTEGER NOT NULL REFERENCES monitored_laws(id),
            snapshot_hash TEXT NOT NULL,
            effective_date TEXT,
            promulgation_date TEXT,
            status TEXT,
            raw_summary_json TEXT,
            fetched_at TEXT NOT NULL,
            is_new INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_law_updates_law ON law_updates(monitored_law_id, fetched_at)"
    )

    # ---- law_analysis ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS law_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            law_update_id INTEGER NOT NULL REFERENCES law_updates(id),
            ai_summary TEXT,
            affected_scope TEXT,
            company_impact TEXT,
            action_needed TEXT,
            prompt_version TEXT,
            analyzed_at TEXT,
            error_message TEXT
        )
        """
    )

    # ---- api_usage (대시보드 자체 OpenAI 호출 비용/호출량 보호용) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS legislative_bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id TEXT NOT NULL UNIQUE,
            bill_no TEXT,
            era TEXT,
            bill_kind TEXT,
            bill_name TEXT NOT NULL,
            proposer_kind TEXT,
            proposer_name TEXT,
            proposed_date TEXT,
            committee_name TEXT,
            committee_result TEXT,
            plenary_result TEXT,
            process_stage TEXT,
            pass_status TEXT,
            link_url TEXT,
            pdf_url TEXT,
            matched_keyword TEXT,
            ai_summary TEXT,
            impact_direction TEXT,
            impact_level TEXT,
            impact_reason TEXT,
            action_needed TEXT,
            analysis_source TEXT,
            analyzed_at TEXT,
            analysis_error TEXT,
            first_seen_at TEXT NOT NULL,
            last_checked_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_legislative_bills_proposed "
        "ON legislative_bills(proposed_date DESC)"
    )
    _ensure_column(connection, "legislative_bills", "ai_summary", "TEXT")
    _ensure_column(connection, "legislative_bills", "impact_direction", "TEXT")
    _ensure_column(connection, "legislative_bills", "impact_level", "TEXT")
    _ensure_column(connection, "legislative_bills", "impact_reason", "TEXT")
    _ensure_column(connection, "legislative_bills", "action_needed", "TEXT")
    _ensure_column(connection, "legislative_bills", "analysis_source", "TEXT")
    _ensure_column(connection, "legislative_bills", "analyzed_at", "TEXT")
    _ensure_column(connection, "legislative_bills", "analysis_error", "TEXT")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS government_legislative_notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notice_id TEXT NOT NULL UNIQUE,
            notice_name TEXT NOT NULL,
            law_type TEXT,
            ministry_name TEXT,
            announcement_no TEXT,
            announcement_date TEXT,
            start_date TEXT,
            end_date TEXT,
            attachment_name TEXT,
            attachment_url TEXT,
            detail_url TEXT,
            view_count INTEGER,
            announcement_type TEXT,
            matched_keyword TEXT,
            first_seen_at TEXT NOT NULL,
            last_checked_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_government_notices_date "
        "ON government_legislative_notices(announcement_date DESC, end_date DESC)"
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_quotes (
            symbol TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            market TEXT,
            base_date TEXT,
            close_price REAL,
            change_value REAL,
            change_rate REAL,
            open_price REAL,
            high_price REAL,
            low_price REAL,
            volume INTEGER,
            market_cap INTEGER,
            fetched_at TEXT NOT NULL
        )
        """
    )
    _ensure_column(connection, "market_quotes", "market_cap", "INTEGER")
    _ensure_column(connection, "market_quotes", "currency", "TEXT")
    _ensure_column(connection, "market_quotes", "source", "TEXT")
    _ensure_column(connection, "market_quotes", "fetch_status", "TEXT NOT NULL DEFAULT 'success'")
    _ensure_column(connection, "market_quotes", "fetch_error", "TEXT")
    _ensure_column(connection, "market_quotes", "last_attempt_at", "TEXT")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS salary_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_code TEXT NOT NULL,
            entity_name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            average_salary_manwon INTEGER NOT NULL,
            source_name TEXT NOT NULL,
            source_url TEXT,
            source_period TEXT,
            collected_date TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            UNIQUE(entity_code, collected_date)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_salary_snapshots_entity_date "
        "ON salary_snapshots(entity_code, collected_date DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS employer_review_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_code TEXT NOT NULL,
            entity_name TEXT NOT NULL,
            source_code TEXT NOT NULL,
            source_name TEXT NOT NULL,
            rating REAL NOT NULL,
            review_count INTEGER,
            source_url TEXT NOT NULL,
            collected_date TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            UNIQUE(entity_code, source_code, collected_date)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_employer_reviews_entity_date "
        "ON employer_review_snapshots(entity_code, source_code, collected_date DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recruitment_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            source_job_id TEXT NOT NULL,
            company_name TEXT,
            title TEXT NOT NULL,
            employment_type TEXT,
            location TEXT,
            deadline TEXT,
            compensation_summary TEXT,
            benefits_summary TEXT,
            ai_summary TEXT,
            treatment_level TEXT,
            source_url TEXT NOT NULL,
            raw_text TEXT,
            posted_at TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            analyzed_at TEXT,
            analysis_error TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(source_name, source_job_id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_recruitment_jobs_seen "
        "ON recruitment_jobs(last_seen_at DESC, is_active)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_quote_history (
            symbol TEXT NOT NULL,
            base_date TEXT NOT NULL,
            close_price REAL NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (symbol, base_date)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS economic_series (
            series_code TEXT NOT NULL,
            observation_date TEXT NOT NULL,
            label TEXT NOT NULL,
            category TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT NOT NULL,
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (series_code, observation_date)
        )
        """
    )
    _ensure_column(connection, "economic_series", "changed_at", "TEXT")
    connection.execute(
        "UPDATE economic_series SET changed_at=fetched_at WHERE changed_at IS NULL"
    )

    # ---- source_data_repository (통합 숫자 데이터 누적 저장소) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS source_data_series (
            series_key TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            label TEXT NOT NULL,
            unit TEXT NOT NULL,
            frequency TEXT NOT NULL,
            aggregation TEXT NOT NULL DEFAULT 'sum',
            source_name TEXT NOT NULL,
            source_url TEXT,
            is_internal INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS source_data_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_key TEXT NOT NULL,
            observation_date TEXT NOT NULL,
            value REAL NOT NULL,
            source_record_key TEXT,
            recorded_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (series_key) REFERENCES source_data_series(series_key),
            UNIQUE(series_key, observation_date)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_data_points_date "
        "ON source_data_points(observation_date)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_data_points_series_date "
        "ON source_data_points(series_key, observation_date)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS source_data_repository_state (
            state_key TEXT PRIMARY KEY,
            state_value TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            called_at TEXT NOT NULL,
            model TEXT,
            request_type TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            estimated_cost REAL,
            success INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_limit_alerts (
            alert_date TEXT NOT NULL,
            limit_type TEXT NOT NULL,
            request_type TEXT NOT NULL,
            call_count INTEGER NOT NULL,
            total_cost REAL NOT NULL,
            claimed_at TEXT NOT NULL,
            sent_at TEXT,
            PRIMARY KEY (alert_date, limit_type)
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_called_at ON api_usage(called_at)")

    # ---- errors (전 구간 공통 오류 로그) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            stage TEXT NOT NULL,
            error_type TEXT,
            error_message TEXT,
            notified INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_errors_occurred_at ON errors(occurred_at)")

    # ---- 공문·자료관리 기준정보 ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_doc_reference_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            code TEXT NOT NULL,
            label TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(kind, code)
        )
        """
    )

    # ---- 공문·자료관리 문서 ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            management_number TEXT NOT NULL UNIQUE,
            receipt_number TEXT,
            manager TEXT NOT NULL,
            receipt_date TEXT NOT NULL,
            organization TEXT NOT NULL,
            case_name TEXT,
            request_content TEXT NOT NULL,
            special_note TEXT,
            requester TEXT,
            contact TEXT,
            email TEXT,
            dispatch_number TEXT,
            reply_date TEXT,
            location TEXT,
            legacy_location TEXT,
            video_exported TEXT NOT NULL DEFAULT '해당없음',
            export_pledge TEXT NOT NULL DEFAULT '해당없음',
            category_code TEXT NOT NULL,
            category_detail TEXT,
            folder_category_code TEXT NOT NULL,
            folder_category_detail TEXT,
            processing_result TEXT NOT NULL DEFAULT '처리 필요',
            registered_by TEXT NOT NULL,
            registered_user_id INTEGER REFERENCES dashboard_users(id),
            registered_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            temp_file_status TEXT NOT NULL DEFAULT 'UPLOADED',
            storage_status TEXT NOT NULL DEFAULT 'UPLOADED',
            sha256_hash TEXT,
            verified_at TEXT,
            error_message TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            duplicate_warning_ack INTEGER NOT NULL DEFAULT 0,
            claim_client TEXT,
            claimed_at TEXT,
            claim_expires_at TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_documents_dates "
        "ON official_documents(receipt_date, registered_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_documents_status "
        "ON official_documents(storage_status, processing_result, is_active)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_receipt_counters (
            year TEXT NOT NULL,
            manager TEXT NOT NULL,
            last_sequence INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (year, manager)
        )
        """
    )
    for column, definition in (
        ("folder_handling_type", "TEXT NOT NULL DEFAULT 'CREATE_NEW'"),
        ("requested_folder_path", "TEXT"),
        ("normalized_unc_path", "TEXT"),
        ("folder_display_name", "TEXT"),
        ("folder_link_status", "TEXT"),
        ("folder_link_note", "TEXT"),
        ("folder_verified_at", "TEXT"),
        ("folder_verified_by_client", "TEXT"),
        ("excel_exported_at", "TEXT"),
        ("deleted_at", "TEXT"),
        ("delete_after", "TEXT"),
        ("deleted_by", "TEXT"),
        ("file_delete_status", "TEXT"),
        ("file_deleted_at", "TEXT"),
        ("file_delete_client", "TEXT"),
        ("file_delete_error", "TEXT"),
    ):
        _ensure_column(connection, "official_documents", column, definition)
    connection.execute(
        """
        UPDATE official_documents SET file_delete_status='PENDING'
        WHERE is_active=0 AND delete_after IS NOT NULL AND file_delete_status IS NULL
        """
    )

    # ---- 공문·자료관리 다중 PDF 첨부 ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_document_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES official_documents(id),
            attachment_type TEXT NOT NULL DEFAULT '일반자료',
            original_filename TEXT NOT NULL,
            temp_filename TEXT,
            final_filename TEXT,
            file_size INTEGER NOT NULL,
            mime_type TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            temp_status TEXT NOT NULL DEFAULT 'UPLOADED',
            final_path TEXT,
            registered_at TEXT NOT NULL,
            stored_at TEXT,
            temp_deleted_at TEXT,
            UNIQUE(document_id, sha256)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_attachments_document "
        "ON official_document_attachments(document_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_attachments_hash "
        "ON official_document_attachments(sha256)"
    )

    # ---- 공문·자료관리 처리이력 ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_document_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER REFERENCES official_documents(id),
            attachment_id INTEGER REFERENCES official_document_attachments(id),
            action TEXT NOT NULL,
            actor TEXT,
            client_name TEXT,
            detail_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_history_document "
        "ON official_document_history(document_id, created_at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_document_change_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_history_id INTEGER UNIQUE,
            document_id INTEGER,
            management_number TEXT,
            attachment_id INTEGER,
            action TEXT NOT NULL,
            actor TEXT,
            client_name TEXT,
            detail_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_change_log_created "
        "ON official_document_change_log(created_at DESC)"
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO official_document_change_log
            (source_history_id, document_id, management_number, attachment_id,
             action, actor, client_name, detail_json, created_at)
        SELECT h.id, h.document_id, d.management_number, h.attachment_id,
               h.action, h.actor, h.client_name, h.detail_json, h.created_at
        FROM official_document_history h
        LEFT JOIN official_documents d ON d.id=h.document_id
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_folder_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_name TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            unc_path TEXT NOT NULL UNIQUE,
            year INTEGER,
            folder_category TEXT,
            file_count INTEGER NOT NULL DEFAULT 0,
            last_modified_at TEXT,
            last_scanned_at TEXT NOT NULL,
            is_available INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_folder_search "
        "ON official_folder_index(year, folder_category, is_available)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_excel_exports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            export_type TEXT NOT NULL,
            exported_by TEXT NOT NULL,
            exported_user_id INTEGER REFERENCES dashboard_users(id),
            exported_at TEXT NOT NULL,
            filter_conditions TEXT,
            record_count INTEGER NOT NULL,
            output_filename TEXT NOT NULL,
            includes_personal_data INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # ---- tips board (migrated from the portfolio JSON board) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tips_articles (
            id TEXT PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '기타',
            tags_json TEXT NOT NULL DEFAULT '[]',
            published_date TEXT NOT NULL,
            updated_date TEXT NOT NULL,
            reading_time TEXT,
            featured INTEGER NOT NULL DEFAULT 0,
            draft INTEGER NOT NULL DEFAULT 0,
            cover_image TEXT,
            author_id INTEGER REFERENCES dashboard_users(id),
            view_count INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            deleted_by INTEGER REFERENCES dashboard_users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tips_public_order "
        "ON tips_articles(is_deleted, draft, featured DESC, published_date DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tips_category "
        "ON tips_articles(category, is_deleted, draft)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tips_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tip_id TEXT NOT NULL REFERENCES tips_articles(id) ON DELETE CASCADE,
            author_id INTEGER NOT NULL REFERENCES dashboard_users(id),
            content TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            deleted_by INTEGER REFERENCES dashboard_users(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tips_comments_tip "
        "ON tips_comments(tip_id, is_deleted, created_at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tips_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tip_id TEXT NOT NULL REFERENCES tips_articles(id) ON DELETE CASCADE,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL UNIQUE,
            mime_type TEXT,
            file_size INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            uploaded_by INTEGER REFERENCES dashboard_users(id),
            created_at TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tips_attachments_tip "
        "ON tips_attachments(tip_id, is_deleted, created_at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS related_sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            description TEXT,
            category TEXT NOT NULL DEFAULT '기타',
            tags TEXT,
            is_pinned INTEGER NOT NULL DEFAULT 0,
            is_public INTEGER NOT NULL DEFAULT 1,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER REFERENCES dashboard_users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_related_sites_order "
        "ON related_sites(is_deleted, is_public, is_pinned DESC, updated_at DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS related_site_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            created_by INTEGER REFERENCES dashboard_users(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO related_site_categories
            (name, created_by, created_at, is_active)
        SELECT category, MIN(created_by), MIN(created_at), 1
        FROM related_sites
        WHERE category<>''
        GROUP BY category
        """
    )
    connection.execute(
        "INSERT OR IGNORE INTO related_site_categories (name) VALUES ('기타')"
    )

    # ---- casino glossary (public reference, admin-managed) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS casino_glossary_terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL CHECK(category IN ('game', 'business')),
            term_ko TEXT NOT NULL,
            term_en TEXT NOT NULL DEFAULT '',
            definition TEXT NOT NULL,
            easy_explanation TEXT NOT NULL,
            aliases TEXT NOT NULL DEFAULT '',
            is_public INTEGER NOT NULL DEFAULT 1,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER REFERENCES dashboard_users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            UNIQUE(category, term_ko)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_casino_glossary_public "
        "ON casino_glossary_terms(is_deleted, is_public, category, term_ko)"
    )
    glossary_timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection.executemany(
        """
        INSERT OR IGNORE INTO casino_glossary_terms
            (category, term_ko, term_en, definition, easy_explanation,
             created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (*term, glossary_timestamp, glossary_timestamp)
            for term in CASINO_GLOSSARY_SEED_TERMS
        ),
    )
    supplied_glossary_terms = (
        CASINO_GLOSSARY_ETG_TERMS + CASINO_GLOSSARY_OPERATIONS_TERMS
    )
    connection.executemany(
        """
        INSERT INTO casino_glossary_terms
            (category, term_ko, term_en, definition, easy_explanation,
             created_at, updated_at)
        SELECT ?, ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM casino_glossary_terms
            WHERE term_ko=? AND is_deleted=0
        )
        """,
        (
            (*term, glossary_timestamp, glossary_timestamp, term[1])
            for term in supplied_glossary_terms
        ),
    )
    connection.executemany(
        """
        UPDATE casino_glossary_terms
        SET term_en=?, definition=?, easy_explanation=?, updated_at=?
        WHERE term_ko=? AND is_deleted=0
        """,
        (
            (term_en, definition, easy_explanation, glossary_timestamp, term_ko)
            for category, term_ko, term_en, definition, easy_explanation
            in supplied_glossary_terms
        ),
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS site_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL,
            updated_by INTEGER REFERENCES dashboard_users(id),
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS content_translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_type TEXT NOT NULL,
            content_id TEXT NOT NULL,
            locale TEXT NOT NULL DEFAULT 'en',
            source_hash TEXT NOT NULL,
            translated_json TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT,
            translated_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(content_type, content_id, locale)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_translations_status "
        "ON content_translations(locale, status, updated_at)"
    )

    # ---- localization management system ----
    # Source strings are deduplicated by their Korean source hash. Languages and
    # translations live in separate rows, so adding a locale never alters schema.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS localization_strings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            language_key TEXT NOT NULL UNIQUE,
            source_text TEXT NOT NULL,
            source_hash TEXT NOT NULL UNIQUE,
            page_name TEXT NOT NULL DEFAULT 'Unknown',
            component TEXT NOT NULL DEFAULT 'Content',
            string_type TEXT NOT NULL DEFAULT 'UI',
            priority TEXT NOT NULL DEFAULT 'Medium',
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS localization_languages (
            language_code TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            is_source INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS localization_translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            string_id INTEGER NOT NULL REFERENCES localization_strings(id) ON DELETE CASCADE,
            language_code TEXT NOT NULL REFERENCES localization_languages(language_code),
            translated_text TEXT,
            status TEXT NOT NULL DEFAULT 'Pending',
            translated_by INTEGER REFERENCES dashboard_users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_translated_at TEXT,
            UNIQUE(string_id, language_code)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS localization_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            string_id INTEGER NOT NULL REFERENCES localization_strings(id) ON DELETE CASCADE,
            source_kind TEXT NOT NULL,
            source_path TEXT NOT NULL,
            locator TEXT NOT NULL DEFAULT '',
            last_seen_at TEXT NOT NULL,
            UNIQUE(string_id, source_kind, source_path, locator)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS localization_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            string_id INTEGER REFERENCES localization_strings(id) ON DELETE SET NULL,
            event_type TEXT NOT NULL,
            language_code TEXT,
            actor_id INTEGER REFERENCES dashboard_users(id),
            detail TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_localization_strings_status "
        "ON localization_strings(status, priority, updated_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_localization_translation_status "
        "ON localization_translations(language_code, status, updated_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_localization_events_created "
        "ON localization_events(created_at DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS localization_glossary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_text TEXT NOT NULL,
            target_text TEXT NOT NULL,
            language_code TEXT NOT NULL DEFAULT 'en'
                REFERENCES localization_languages(language_code),
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by INTEGER REFERENCES dashboard_users(id),
            UNIQUE(source_text, language_code)
        )
        """
    )
    localization_now = datetime.now(timezone.utc).isoformat()
    for language_code, display_name, is_source in (
        ('ko', '한국어', 1), ('en', 'English', 0),
        ('ja', '日本語', 0), ('yue-HK', '廣東話', 0),
    ):
        connection.execute(
            """INSERT OR IGNORE INTO localization_languages
                   (language_code, display_name, is_source, is_active, created_at)
               VALUES (?, ?, ?, 1, ?)""",
            (language_code, display_name, is_source, localization_now),
        )
    for source_text, target_text in (
        ('카지노 인텔리전스', 'Casino Intelligence'),
        ('AI 의견', 'AI Opinion'),
        ('기업정보', 'Company Profile'),
        ('리서치', 'Research'),
        ('기업 360°', 'Company 360°'),
        ('파라다이스', 'Paradise'),
        ('강원랜드', 'Kangwon Land'),
        ('인스파이어', 'INSPIRE'),
    ):
        connection.execute(
            """INSERT OR IGNORE INTO localization_glossary
                   (source_text, target_text, language_code, created_at, updated_at)
               VALUES (?, ?, 'en', ?, ?)""",
            (source_text, target_text, localization_now, localization_now),
        )

    # ---- overseas casino news (Macau / Japan) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS overseas_news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_key TEXT NOT NULL UNIQUE,
            region TEXT NOT NULL,
            original_title TEXT NOT NULL,
            original_summary TEXT,
            title_ko TEXT,
            summary_ko TEXT,
            publisher TEXT,
            original_url TEXT NOT NULL,
            source_feed TEXT NOT NULL,
            published_at TEXT,
            collected_at TEXT NOT NULL,
            translated_at TEXT,
            translation_status TEXT NOT NULL DEFAULT 'pending',
            translation_error TEXT,
            category TEXT,
            impact_direction TEXT,
          importance_score INTEGER,
          ai_analysis TEXT,
          analyzed_at TEXT,
          canonical_url TEXT,
          analysis_basis TEXT,
          retrieval_status TEXT,
          source_citations_json TEXT,
          gemini_model TEXT,
          gemini_analyzed_at TEXT,
          analysis_error TEXT
        )
        """
    )
    _ensure_column(connection, "overseas_news_articles", "category", "TEXT")
    _ensure_column(connection, "overseas_news_articles", "impact_direction", "TEXT")
    _ensure_column(connection, "overseas_news_articles", "importance_score", "INTEGER")
    _ensure_column(connection, "overseas_news_articles", "ai_analysis", "TEXT")
    _ensure_column(connection, "overseas_news_articles", "analyzed_at", "TEXT")
    _ensure_column(connection, "overseas_news_articles", "canonical_url", "TEXT")
    _ensure_column(connection, "overseas_news_articles", "analysis_basis", "TEXT")
    _ensure_column(connection, "overseas_news_articles", "retrieval_status", "TEXT")
    _ensure_column(connection, "overseas_news_articles", "source_citations_json", "TEXT")
    _ensure_column(connection, "overseas_news_articles", "gemini_model", "TEXT")
    _ensure_column(connection, "overseas_news_articles", "gemini_analyzed_at", "TEXT")
    _ensure_column(connection, "overseas_news_articles", "analysis_error", "TEXT")
    _ensure_column(connection, "overseas_news_articles", "analysis_provider", "TEXT")
    _ensure_column(connection, "overseas_news_articles", "analysis_model", "TEXT")
    _ensure_column(connection, "overseas_news_articles", "web_verified_at", "TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_overseas_news_region_date "
        "ON overseas_news_articles(region, published_at DESC, collected_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_overseas_news_translation "
        "ON overseas_news_articles(translation_status, collected_at)"
    )

    # api_usage started as an OpenAI-only daily budget ledger. Keep that data
    # intact and extend the same append-only ledger for per-article Gemini usage.
    _ensure_column(connection, "api_usage", "provider", "TEXT")
    _ensure_column(connection, "api_usage", "article_id", "INTEGER")
    _ensure_column(connection, "api_usage", "article_title", "TEXT")
    _ensure_column(connection, "api_usage", "article_url", "TEXT")
    _ensure_column(connection, "api_usage", "request_stage", "TEXT")
    _ensure_column(connection, "api_usage", "thought_tokens", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "api_usage", "total_tokens", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "api_usage", "search_query_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "api_usage", "input_cost_usd", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "api_usage", "output_cost_usd", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "api_usage", "search_cost_usd", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "api_usage", "usd_krw_rate", "REAL")
    _ensure_column(connection, "api_usage", "estimated_cost_krw", "REAL NOT NULL DEFAULT 0")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_api_usage_provider_called "
        "ON api_usage(provider, called_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_api_usage_article "
        "ON api_usage(article_id, called_at DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS overseas_news_sync_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_checked_at TEXT,
            last_changed_at TEXT,
            last_status TEXT,
            last_error TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )

    defaults = {
        "category": [
            ("01-1", "01-1. 공문접수"), ("01-2", "01-2. 공문발송"),
            ("02", "02. 문서접수(공문 外)"), ("03", "03. 수사협조요청"),
            ("04", "04. 영상반출확약서"), ("OTHER", "기타"),
        ],
        "folder_category": [
            ("071", "071. 본사"), ("072", "072. 수사기관"), ("073", "073. 문체부"),
            ("074", "074. 카지노협회"), ("075", "075. 국회"),
            ("076", "076. 사행성감독위원회"), ("077", "077. 고객"),
            ("078", "078. 기타"), ("079", "079. 직원"),
        ],
    }
    now_iso = datetime.now(timezone.utc).isoformat()
    for kind, values in defaults.items():
        for order, (code, label) in enumerate(values, 1):
            connection.execute(
                """
                INSERT OR IGNORE INTO official_doc_reference_values
                    (kind, code, label, active, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?, ?)
                """,
                (kind, code, label, order, now_iso, now_iso),
            )

    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
