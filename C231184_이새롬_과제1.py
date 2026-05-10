import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


# =====================================================
# [1] 페이지 설정
# =====================================================
st.set_page_config(page_title="APP 비용 최소화 시스템", layout="wide")
st.title("C231184_이새롬_과제1")
st.caption("수요·운영조건·비용 파라미터 변경에 따른 총괄생산계획 수립 및 시각화 대시보드")


# =====================================================
# [2] 사이드바 - 제약 및 비용 설정
# =====================================================
st.sidebar.header("표시 단위 설정")
unit_label = st.sidebar.selectbox("금액 표시 단위", ["원", "천원", "만원", "백만원"])
unit_div = {"원": 1, "천원": 1000, "만원": 10000, "백만원": 1000000}[unit_label]

st.sidebar.header("초기/최종 제약조건")
initial_workers = st.sidebar.number_input("1월초 종업원 수 (명)", min_value=1, value=80, step=1)
initial_inventory = st.sidebar.number_input("1월초 기초 재고 (개)", min_value=0, value=1000, step=1)
initial_backlog = st.sidebar.number_input("1월초 부재고 (개)", min_value=0, value=0, step=1)
target_inventory = st.sidebar.number_input("6월말 목표 재고 (최소)", min_value=0, value=500, step=1)
require_monthly_no_backlog = st.sidebar.checkbox(
    "월별 부재고도 0이어야 함",
    value=False,
    help="체크하면 모든 월의 부재고가 0인 계획만 제약조건을 만족한 것으로 봅니다. 체크하지 않으면 부재고 비용을 부과하고 6월말에는 전량 해소하는 모델입니다.",
)

st.sidebar.header("월별 수요 계획")
months = ["1월", "2월", "3월", "4월", "5월", "6월"]
default_demands = [1600, 3000, 3200, 3800, 2200, 2200]
demands = [
    st.sidebar.number_input(f"{m} 수요", min_value=0, value=d, step=1)
    for m, d in zip(months, default_demands)
]

st.sidebar.header("운영 및 제약 조건")
work_days = st.sidebar.number_input("월 작업일수", min_value=1, value=20, step=1)
daily_hours = st.sidebar.number_input("일 작업시간", min_value=0.1, value=8.0, step=0.5)
std_time = st.sidebar.number_input("제품 1개 표준시간(h)", min_value=0.1, value=4.0, step=0.1)
ot_limit = st.sidebar.number_input("인당 최대 잔업(h/월)", min_value=0.0, value=10.0, step=1.0)
sub_limit = st.sidebar.number_input("월 최대 외주 한도(개)", min_value=0, value=500, step=1)

st.sidebar.header("비용 정보 (단위: 원)")
w_reg = st.sidebar.number_input("정규 임금 (원/시간)", min_value=0, value=4000, step=100)
w_ot = st.sidebar.number_input("잔업 임금 (원/시간)", min_value=0, value=6000, step=100)
m_cost = st.sidebar.number_input("재료비 (원/개)", min_value=0, value=10000, step=100)
s_cost = st.sidebar.number_input("외주 비용 (원/개)", min_value=0, value=15000, step=100)
h_cost = st.sidebar.number_input("재고유지비 (원/개/월)", min_value=0, value=2000, step=100)
b_cost = st.sidebar.number_input("부재고 비용 (원/개/월)", min_value=0, value=5000, step=100)
h_hire = st.sidebar.number_input("고용 비용 (원/인)", min_value=0, value=300000, step=10000)
f_fire = st.sidebar.number_input("해고 비용 (원/인)", min_value=0, value=500000, step=10000)
sales_price = st.sidebar.number_input(
    "판매 단가 (원/개, 참고용)",
    min_value=0,
    value=40000,
    step=1000,
    help="본 앱의 최적화 목적함수는 총비용 최소화입니다. 판매 단가는 매출/이익 참고 지표 계산에만 사용됩니다.",
)


# =====================================================
# [3] 공통 함수
# =====================================================
def is_plan_feasible(df: pd.DataFrame) -> bool:
    final_ok = (df["재고"].iloc[-1] >= target_inventory) and (df["부재고"].iloc[-1] == 0)
    monthly_ok = (df["부재고"] == 0).all() if require_monthly_no_backlog else True
    return bool(final_ok and monthly_ok)


def get_level_search_upper_bound() -> int:
    total_required_units = max(0, sum(demands) + target_inventory + initial_backlog - initial_inventory)
    avg_required_units = total_required_units / len(months)
    monthly_units_per_worker = (work_days * daily_hours) / std_time
    avg_required_workers = math.ceil(avg_required_units / monthly_units_per_worker)

    peak_required_units = max(demands) + target_inventory + initial_backlog
    peak_required_workers = math.ceil(peak_required_units / monthly_units_per_worker)

    upper_bound = max(200, initial_workers * 2, avg_required_workers * 3, peak_required_workers * 2)
    return int(min(max(upper_bound, 1), 5000))


def add_display_cost_columns(df: pd.DataFrame) -> pd.DataFrame:
    view_df = df.copy()
    cost_columns = [
        "정규노무비",
        "재료비",
        "잔업비",
        "외주비",
        "고용/해고비",
        "재고유지비",
        "부재고비",
        "총비용",
    ]
    for col in cost_columns:
        view_df[col] = (view_df[col] / unit_div).round(1)

    rename_map = {col: f"{col} ({unit_label})" for col in cost_columns}
    return view_df.rename(columns=rename_map)


def run_app_logic(strategy, manual_workers=None):
    results = []
    curr_inv = initial_inventory
    curr_workers = initial_workers
    curr_backlog = initial_backlog

    for i in range(6):
        if manual_workers is not None:
            target_workers = manual_workers[i] if isinstance(manual_workers, list) else manual_workers
        else:
            req_prod = max(0, demands[i] + curr_backlog - curr_inv + (target_inventory if i == 5 else 0))
            if strategy == "Chase":
                target_workers = math.ceil(req_prod * std_time / (work_days * daily_hours))
                target_workers = max(1, target_workers)
            else:
                target_workers = curr_workers

        target_workers = int(max(1, target_workers))
        hired = max(0, target_workers - curr_workers)
        fired = max(0, curr_workers - target_workers)
        curr_workers = target_workers

        reg_cap = (curr_workers * work_days * daily_hours) / std_time
        ot_cap = (curr_workers * ot_limit) / std_time

        if strategy == "Level":
            reg_prod = reg_cap
            ot_prod = 0
            sub_prod = 0
        else:
            needed = max(0, demands[i] + curr_backlog - curr_inv + (target_inventory if i == 5 else 0))
            reg_prod = min(needed, reg_cap)
            ot_prod = min(ot_cap, max(0, needed - reg_prod))
            sub_prod = min(sub_limit, max(0, needed - reg_prod - ot_prod))

        total_prod = reg_prod + ot_prod + sub_prod

        utilization = (total_prod / reg_cap * 100) if reg_cap > 0 else 0
        ot_hours = ot_prod * std_time

        available = curr_inv + total_prod
        current_demand = demands[i] + curr_backlog
        end_inv = max(0, available - current_demand)
        end_backlog = max(0, current_demand - available)

        cost_regular_labor = curr_workers * work_days * daily_hours * w_reg
        cost_material = total_prod * m_cost
        cost_ot = ot_hours * w_ot
        cost_sub = sub_prod * s_cost
        cost_hr = hired * h_hire + fired * f_fire
        cost_inv = end_inv * h_cost
        cost_back = end_backlog * b_cost
        total_cost = (
            cost_regular_labor
            + cost_material
            + cost_ot
            + cost_sub
            + cost_hr
            + cost_inv
            + cost_back
        )

        results.append(
            {
                "월": months[i],
                "수요": int(demands[i]),
                "작업자": int(curr_workers),
                "고용": int(hired),
                "해고": int(fired),
                "정규생산": round(reg_prod, 1),
                "잔업생산": round(ot_prod, 1),
                "외주생산": round(sub_prod, 1),
                "총생산": round(total_prod, 1),
                "재고": round(end_inv, 1),
                "부재고": round(end_backlog, 1),
                "잔업시간": round(ot_hours, 1),
                "활용률(%)": round(utilization, 1),
                "정규노무비": round(cost_regular_labor),
                "재료비": round(cost_material),
                "잔업비": round(cost_ot),
                "외주비": round(cost_sub),
                "고용/해고비": round(cost_hr),
                "재고유지비": round(cost_inv),
                "부재고비": round(cost_back),
                "총비용": round(total_cost),
            }
        )

        curr_inv = end_inv
        curr_backlog = end_backlog

    return pd.DataFrame(results)


def render_plan_dashboard(df: pd.DataFrame, title_prefix: str):
    st.markdown(f"### {title_prefix} 결과표")
    st.dataframe(add_display_cost_columns(df), use_container_width=True)

    total_cost = df["총비용"].sum()
    total_revenue = sum(demands) * sales_price
    estimated_profit = total_revenue - total_cost

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(f"총비용 ({unit_label})", f"{total_cost / unit_div:,.1f}")
    k2.metric("6월말 재고", f"{df['재고'].iloc[-1]:,.1f} 개")
    k3.metric("6월말 부재고", f"{df['부재고'].iloc[-1]:,.1f} 개")
    k4.metric(f"참고 이익 ({unit_label})", f"{estimated_profit / unit_div:,.1f}")

    st.markdown("### 다각도 계획 분석")
    g1, g2 = st.columns(2)

    with g1:
        fig1 = go.Figure(
            [
                go.Bar(x=months, y=df["수요"], name="수요"),
                go.Scatter(x=months, y=df["총생산"], name="총 생산", line=dict(color="red", width=3)),
            ]
        )
        fig1.update_layout(title="수요 대비 총 생산량 추이", margin=dict(t=40, b=0, l=0, r=0))
        st.plotly_chart(fig1, use_container_width=True)

        fig3 = go.Figure()
        fig3.add_trace(go.Bar(x=months, y=df["작업자"], name="투입 작업자 수", yaxis="y1", marker_color="lightblue"))
        fig3.add_trace(go.Scatter(x=months, y=df["활용률(%)"], name="생산 활용률(%)", yaxis="y2", line=dict(color="orange")))
        fig3.update_layout(
            title="인력 투입 및 생산능력 활용률",
            yaxis=dict(title="작업자 수"),
            yaxis2=dict(title="활용률(%)", overlaying="y", side="right"),
            margin=dict(t=40, b=0, l=0, r=0),
        )
        st.plotly_chart(fig3, use_container_width=True)

    with g2:
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=months, y=df["재고"], fill="tozeroy", name="기말 재고", line=dict(color="green")))
        fig2.add_trace(go.Scatter(x=months, y=df["부재고"], fill="tozeroy", name="부재고(Backlog)", line=dict(color="red")))
        fig2.update_layout(title="재고 및 부재고 변동", margin=dict(t=40, b=0, l=0, r=0))
        st.plotly_chart(fig2, use_container_width=True)

        cost_sums = {
            "정규노무비": df["정규노무비"].sum(),
            "재료비": df["재료비"].sum(),
            "잔업비": df["잔업비"].sum(),
            "외주비": df["외주비"].sum(),
            "고용/해고비": df["고용/해고비"].sum(),
            "재고유지비": df["재고유지비"].sum(),
            "부재고비": df["부재고비"].sum(),
        }
        cost_sums = {k: v for k, v in cost_sums.items() if v > 0}
        fig4 = px.pie(values=list(cost_sums.values()), names=list(cost_sums.keys()), title="총비용 세부 구성비")
        fig4.update_layout(margin=dict(t=40, b=0, l=0, r=0))
        st.plotly_chart(fig4, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="계획 결과 CSV 다운로드",
        data=csv,
        file_name=f"{title_prefix}_APP_계획.csv",
        mime="text/csv",
    )


def render_feasibility_message(df: pd.DataFrame):
    final_inventory_ok = df["재고"].iloc[-1] >= target_inventory
    final_backlog_ok = df["부재고"].iloc[-1] == 0
    monthly_backlog_ok = (df["부재고"] == 0).all()

    v1, v2, v3, v4 = st.columns(4)
    v1.write(f"1월초 부재고 0: {'✅' if initial_backlog == 0 else '❌'}")
    v2.write(f"6월말 재고 {target_inventory}개 이상: {'✅' if final_inventory_ok else '❌'}")
    v3.write(f"6월말 부재고 0: {'✅' if final_backlog_ok else '❌'}")
    v4.write(f"월별 부재고 0: {'✅' if monthly_backlog_ok else '❌'}")

    if require_monthly_no_backlog and not monthly_backlog_ok:
        st.warning("현재 설정은 월별 부재고를 허용하지 않으므로, 부재고가 발생한 월이 있는 계획은 제약조건 미충족입니다.")
    elif not require_monthly_no_backlog and not monthly_backlog_ok:
        st.info("현재 설정은 월별 부재고를 허용하고 부재고 비용을 부과합니다. 단, 6월말 부재고는 0이어야 합니다.")


# =====================================================
# [4] UI 레이아웃
# =====================================================
tab1, tab2 = st.tabs(["수동 조정", "자동 계획 생성"])

with tab1:
    st.subheader("사용자 직접 조정 모드")
    m_strat = st.radio("전략 선택", ["Level", "Chase"], horizontal=True, key="manual_strategy")

    if m_strat == "Level":
        m_workers = st.slider("고정 작업자 수", 1, max(200, initial_workers * 2), initial_workers)
        res_df = run_app_logic("Level", m_workers)
    else:
        cols = st.columns(6)
        c_list = [
            cols[j].number_input(
                f"{months[j]} 작업자",
                min_value=1,
                value=initial_workers,
                step=1,
                key=f"manual_chase_workers_{j}",
            )
            for j in range(6)
        ]
        res_df = run_app_logic("Chase", c_list)

    render_plan_dashboard(res_df, "수동 계획")

with tab2:
    st.subheader("시스템 알고리즘 결과")
    st.info(
        "Level은 고정 작업자 수를 바꿔가며 총비용이 가장 낮은 계획을 탐색합니다. "
        "Chase는 비용 최적화가 아니라 월별 수요를 따라가도록 필요 작업자 수를 자동 산정하는 방식입니다."
    )

    a_strat = st.radio(
        "알고리즘 대상 선택",
        ["Level (비용 최소화 최적 탐색)", "Chase (수요 기반 자동 계획 생성)"],
        horizontal=True,
        key="auto_strategy",
    )

    btn_text = "최적 고정인원 탐색 실행" if "Level" in a_strat else "자동 수요추종 계획 생성"

    if st.button(btn_text, type="primary"):
        best_df = None

        if "Level" in a_strat:
            best_cost = float("inf")
            search_upper = get_level_search_upper_bound()

            for w in range(1, search_upper + 1):
                tdf = run_app_logic("Level", w)
                if is_plan_feasible(tdf):
                    current_cost = tdf["총비용"].sum()
                    if current_cost < best_cost:
                        best_cost = current_cost
                        best_df = tdf

            if best_df is not None:
                st.success(f"[Level] 제약조건을 만족하는 최소 비용 탐색 완료! 탐색 범위: 1명~{search_upper}명")
        else:
            best_df = run_app_logic("Chase", None)
            if not is_plan_feasible(best_df):
                best_df = None

            if best_df is not None:
                st.success("[Chase] 수요 기반 자동 계획 생성 완료! 단, 이는 비용 최적해가 아니라 수요추종 계획입니다.")

        if best_df is not None:
            render_plan_dashboard(best_df, "자동 계획")
        else:
            st.error(
                "현재 설정된 제약조건 내에서는 조건을 만족하는 계획을 찾지 못했습니다. "
                "작업시간, 잔업 한도, 외주 한도, 월별 부재고 허용 여부 또는 목표 재고 조건을 조정해보세요."
            )


# =====================================================
# [5] 실시간 제약 검증
# =====================================================
st.divider()
st.markdown("### 현재 수동 계획의 제약조건 준수 여부")
render_feasibility_message(res_df)

if is_plan_feasible(res_df):
    st.success("현재 수동 계획은 선택한 제약조건을 만족합니다.")
else:
    st.warning("현재 수동 계획은 선택한 제약조건을 만족하지 않습니다. 작업자 수, 수요, 운영 조건을 조정해보세요.")
