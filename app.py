import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime, date, time, timedelta

# --- DB接続 ---
engine = create_engine("sqlite:///car_reservations.db", echo=False)

# --- テーブル作成 ---
with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            date TEXT,
            start_time TEXT,
            end_time TEXT,
            car TEXT,
            status TEXT DEFAULT '予約済'
        )
    """))

# --- セッション初期化 ---
if 'last_end_time' not in st.session_state:
    st.session_state.last_end_time = None
if 'last_end_date' not in st.session_state:
    st.session_state.last_end_date = None
if 'cancel_id' not in st.session_state:
    st.session_state.cancel_id = None

# --- 過去日の自動キャンセル ---
today_str = str(date.today())
with engine.begin() as conn:
    conn.execute(
        text("UPDATE reservations SET status='キャンセル済' WHERE date < :today AND status='予約済'"),
        {"today": today_str}
    )

# --- キャンセル処理 ---
if st.session_state.cancel_id is not None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE reservations SET status='キャンセル済' WHERE id=:id"),
            {"id": st.session_state.cancel_id}
        )
    st.session_state.cancel_id = None
    st.rerun()

# --- ページタイトル ---
st.header("🚗 車予約フォーム")

# --- 予約フォーム ---
with st.form("reserve_form", clear_on_submit=True):
    name = st.text_input("名前")
    reserve_date = st.date_input("使用日", min_value=date.today(), value=date.today())
    car = st.selectbox("車種", ["VOXY"])

    # 別日なら前回終了時刻リセット
    if st.session_state.last_end_date != reserve_date:
        st.session_state.last_end_time = None
        st.session_state.last_end_date = reserve_date

    # --- 既存予約取得 ---
    with engine.connect() as conn:
        df_existing = pd.read_sql(
            "SELECT * FROM reservations WHERE date=:date AND car=:car AND status='予約済'",
            conn, params={"date": str(reserve_date), "car": car}
        )

    # --- 全スロット作成 ---
    all_slots = [time(h, m) for h in range(0, 24) for m in range(0, 60, 15)]

    # 既存予約の該当スロット
    unavailable_slots = []
    for _, row in df_existing.iterrows():
        s = datetime.strptime(row['start_time'], "%H:%M")
        e = datetime.strptime(row['end_time'], "%H:%M")
        t = s
        while t < e:
            unavailable_slots.append(t.time())
            t += timedelta(minutes=15)

    # 開始時刻として使用可能なスロット
    available_start_slots = [
        t for t in all_slots
        if (st.session_state.last_end_time is None or t >= st.session_state.last_end_time)
        and t not in unavailable_slots
    ]

    if not available_start_slots:
        st.warning("この日は予約できる時間がありません。")
        st.stop()

    start_time = st.selectbox(
        "開始時刻",
        available_start_slots,
        format_func=lambda x: f"{x.hour:02d}:{x.minute:02d}"
    )

    # --- 利用時間チェック ---
    start_dt = datetime.combine(reserve_date, start_time)
    durations = [15 * i for i in range(2, 24 * 4 + 1)]  # 30分～24時間
    valid_durations = []

    for d in durations:
        end_dt = start_dt + timedelta(minutes=d)

        with engine.connect() as conn:
            overlap = pd.read_sql(
                """
                SELECT * FROM reservations
                WHERE car = :car
                AND date = :date
                AND status='予約済'
                AND NOT (end_time <= :start OR start_time >= :end)
                """,
                conn,
                params={
                    "car": car,
                    "date": str(reserve_date),
                    "start": start_time.strftime("%H:%M"),
                    "end": end_dt.strftime("%H:%M")
                }
            )

        if overlap.empty:
            valid_durations.append(d)

    if not valid_durations:
        st.warning("利用可能な時間がありません。")
        st.stop()

    duration_minutes = st.selectbox(
        "利用時間",
        valid_durations,
        format_func=lambda x: "24時間(1日)" if x == 1440 else f"{x//60}時間{x%60}分"
    )

    submitted = st.form_submit_button("予約する")

# --- 予約登録 ---
if submitted:
    if not name.strip():
        st.error("名前を入力してください。")
    else:
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO reservations (name, date, start_time, end_time, car)
                    VALUES (:name, :date, :start, :end, :car)
                """),
                {
                    "name": name,
                    "date": str(reserve_date),
                    "start": start_time.strftime("%H:%M"),
                    "end": end_dt.strftime("%H:%M"),
                    "car": car
                }
            )

        st.session_state.last_end_time = end_dt.time()
        st.success(f"{name} さんの予約を追加しました！")
        st.rerun()

# --- 表示用フォーマット関数 ---
def format_row(row):
    # 開始・終了の datetime
    start_full = datetime.strptime(f"{row['date']} {row['start_time']}", "%Y-%m-%d %H:%M")
    end_full = datetime.strptime(f"{row['date']} {row['end_time']}", "%Y-%m-%d %H:%M")
    if end_full <= start_full:  # 翌日終了の場合
        end_full += timedelta(days=1)

    # 利用時間計算
    use_minutes = int((end_full - start_full).total_seconds() // 60)
    use_str = f"{use_minutes // 60}時間{use_minutes % 60}分"

    # 表示形式: 開始日 利用時間 開始時刻~終了日終了時刻(〇時間〇分)
    return f"利用者{row['name']} 利用日：{row['date']}  {row['start_time']}~{end_full.strftime('%Y-%m-%d %H:%M')}　利用時間({use_str})"




# --- 予約一覧 ---
st.header("📅 予約一覧")

with engine.connect() as conn:
    df_all = pd.read_sql("SELECT * FROM reservations ORDER BY date, start_time", conn)

if df_all.empty:
    st.write("予約はまだありません。")
else:
    df_reserved = df_all[df_all["status"] == "予約済"]
    df_canceled = df_all[df_all["status"] == "キャンセル済"]

    # --- 予約済み ---
    st.subheader("予約済み")
    if df_reserved.empty:
        st.write("なし")
    else:
        for _, row in df_reserved.iterrows():
            st.write(format_row(row))
            if st.button("キャンセル", key=f"cancel_{row['id']}"):
                st.session_state.cancel_id = row["id"]
                st.rerun()

    # --- キャンセル済み ---
    st.subheader("キャンセル済み")
    if df_canceled.empty:
        st.write("なし")
    else:
        for _, row in df_canceled.iterrows():
            st.write("❌ " + format_row(row))
