# ✅ Golf BANK v3.3 主程式 Part 1：初始化、載入、雲端整合、狀態管理
import streamlit as st
import pandas as pd
import json
import qrcode
import io
import os
import time
from io import BytesIO
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ========== 基本設定 ==========
BASE_URL = "https://your-streamlit-app-url/"  # 修改為實際部署網址
st.set_page_config(page_title="🏌️ Golf BANK v3.3", layout="wide")
st.title("🏌️ Golf BANK 系統")

# ========== 載入資料 ==========
@st.cache_data(ttl=3600)
def load_course_db():
    return pd.read_csv("course_db.csv")

@st.cache_data(ttl=3600)
def load_players():
    return pd.read_csv("players.csv")

try:
    course_df = load_course_db()
    st.toast("✅ 球場資料載入成功", icon="⛳")
except:
    st.error("❌ 找不到 course_db.csv")
    st.stop()

try:
    players_df = load_players()
    all_players = players_df["name"].dropna().tolist()
    st.toast("✅ 球員名單載入成功", icon="👤")
except:
    st.error("❌ 找不到 players.csv")
    st.stop()

# ========== Google Drive 整合 ==========
@st.cache_resource(show_spinner="連接 Google Drive...")
def connect_drive():
    raw = dict(st.secrets["gdrive"])
    raw["private_key"] = raw["private_key"].replace("\\n", "\n")
    credentials = service_account.Credentials.from_service_account_info(
        raw, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=credentials)

drive_service = connect_drive()

@st.cache_resource
def create_or_get_folder():
    query = "mimeType='application/vnd.google-apps.folder' and name='GolfBank_Folder' and trashed=false"
    res = drive_service.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    items = res.get("files", [])
    if items:
        return items[0]["id"]
    folder = drive_service.files().create(
        body={"name": "GolfBank_Folder", "mimeType": "application/vnd.google-apps.folder"},
        fields="id", supportsAllDrives=True
    ).execute()
    return folder["id"]

GAMES_FOLDER_ID = create_or_get_folder()

def save_game_to_drive(data, game_id):
    try:
        content = io.BytesIO(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        media = MediaIoBaseUpload(content, mimetype='application/json')
        query = f"name='game_{game_id}.json' and '{GAMES_FOLDER_ID}' in parents"
        existing = drive_service.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files", [])
        if existing:
            drive_service.files().update(fileId=existing[0]["id"], media_body=media, supportsAllDrives=True).execute()
        else:
            drive_service.files().create(
                body={"name": f"game_{game_id}.json", "parents": [GAMES_FOLDER_ID]},
                media_body=media, fields="id", supportsAllDrives=True
            ).execute()
        time.sleep(1)
        st.toast("☁️ 雲端儲存成功", icon="💾")
    except Exception as e:
        st.error("❌ 儲存失敗: " + str(e))

def load_game_from_drive(game_id):
    try:
        query = f"name='game_{game_id}.json' and '{GAMES_FOLDER_ID}' in parents"
        files = drive_service.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files", [])
        if not files:
            return None
        content = drive_service.files().get_media(fileId=files[0]["id"]).execute()
        return json.loads(content)
    except:
        return None

# ========== 狀態管理 ==========
if "game_id" in st.query_params and not st.session_state.get("mode_initialized"):
    st.session_state.update({
        "mode": "viewer",
        "current_game_id": st.query_params["game_id"],
        "mode_initialized": True
    })
    st.rerun()

if "mode" not in st.session_state:
    st.session_state.mode = "setup"
if "current_game_id" not in st.session_state:
    st.session_state.current_game_id = ""
# ✅ Golf BANK v3.3 主程式 Part 2：選手設定、成績輸入、勝負邏輯、總結畫面

# ========== 選手設定 ==========
if st.session_state.mode == "setup":
    st.header("👥 選擇參賽球員")
    selected_players = st.multiselect("從名單中選擇 (最多4人)", all_players, max_selections=4)

    if len(selected_players) >= 2:
        with st.form("game_setup"):
            st.subheader("球員差點設定")
            cols = st.columns(len(selected_players))
            handicaps = {}
            for i, p in enumerate(selected_players):
                with cols[i]:
                    handicaps[p] = st.number_input(f"{p} 差點", 0, 54, 0)

            course = st.selectbox("選擇球場", course_df["course_name"].unique())
            area_df = course_df[course_df["course_name"] == course]
            valid_areas = area_df.groupby("area").filter(lambda x: len(x)==9)["area"].unique()
            col1, col2 = st.columns(2)
            with col1:
                a1 = st.selectbox("前九洞", valid_areas)
            with col2:
                a2 = st.selectbox("後九洞", [x for x in valid_areas if x != a1])

            bet = st.number_input("每人賭金", 10, 1000, 100, 10)
            if st.form_submit_button("🚀 開始比賽"):
                df1 = area_df[area_df["area"] == a1].sort_values("hole")
                df2 = area_df[area_df["area"] == a2].sort_values("hole")

                game_id = datetime.now().strftime("%Y%m%d_%H%M%S")
                game_data = {
                    "game_id": game_id,
                    "players": selected_players,
                    "handicaps": handicaps,
                    "par": df1["par"].tolist() + df2["par"].tolist(),
                    "hcp": df1["hcp"].tolist() + df2["hcp"].tolist(),
                    "bet_per_person": bet,
                    "scores": {p: {} for p in selected_players},
                    "running_points": {p: 0 for p in selected_players},
                    "current_titles": {p: "" for p in selected_players},
                    "hole_logs": [],
                    "completed": 0,
                    "carryover": 0
                }
                save_game_to_drive(game_data, game_id)
                st.session_state.current_game_id = game_id
                st.session_state.mode = "input"
                st.rerun()

# ========== 成績輸入 ==========
elif st.session_state.mode == "input":
    game_id = st.session_state.current_game_id
    game_data = load_game_from_drive(game_id)
    if not game_data:
        st.error("❌ 無法讀取比賽資料")
        st.stop()

    hole = game_data["completed"]
    if hole >= 18:
        st.success("🏁 比賽已完成，下方為最終結算：")
        players = game_data["players"]
        scores = game_data["scores"]
        par = game_data["par"]
        hcp = game_data["hcp"]
        handicaps = game_data["handicaps"]

        results = {p: {"勝": 0, "平": 0, "負": 0, "積分": game_data["running_points"][p]} for p in players}

        for h in range(18):
            current_par = par[h]
            current_hcp = hcp[h]
            adj = {}
            for p in players:
                adjust = sum(1 for q in players if p != q and (handicaps[q] - handicaps[p]) > 0 and current_hcp <= (handicaps[q] - handicaps[p]))
                adj[p] = scores[p][str(h)] - adjust
            victory = {p: sum(1 for q in players if p != q and adj[p] < adj[q]) for p in players}
            winners = [p for p, v in victory.items() if v == len(players)-1]
            for p in players:
                if len(winners) == 1:
                    results[p]["勝"] += 1 if p == winners[0] else 0
                    results[p]["負"] += 1 if p != winners[0] else 0
                else:
                    results[p]["平"] += 1

        final_rows = []
        for p in players:
            r = results[p]
            final_rows.append({
                "球員": p,
                "勝": r["勝"], "平": r["平"], "負": r["負"],
                "積分": r["積分"],
                "結算金額": r["積分"] * game_data["bet_per_person"]
            })
        df_final = pd.DataFrame(final_rows).sort_values("積分", ascending=False, ignore_index=True)
        st.dataframe(df_final, use_container_width=True)
        st.stop()

    st.subheader(f"第 {hole+1} 洞 成績輸入")
    st.write(f"Par {game_data['par'][hole]} | HCP {game_data['hcp'][hole]}")

    scores = {}
    for p in game_data["players"]:
        scores[p] = st.number_input(f"{p} 桿數", 1, 15, game_data['par'][hole], key=f"hole_{hole}_{p}")

    if st.button("✅ 確認本洞成績"):
        current_par = game_data["par"][hole]
        current_hcp = game_data["hcp"][hole]
        adj = {}
        for p in game_data["players"]:
            adjust = sum(1 for q in game_data["players"] if p != q and (game_data["handicaps"][q] - game_data["handicaps"][p]) > 0 and current_hcp <= (game_data["handicaps"][q] - game_data["handicaps"][p]))
            adj[p] = scores[p] - adjust

        victory = {p: sum(1 for q in adj if p != q and adj[p] < adj[q]) for p in adj}
        winners = [p for p in victory if victory[p] == len(game_data["players"])-1]

        if len(winners) == 1:
            w = winners[0]
            birdie = scores[w] <= current_par - 1
            total = 1 + game_data["carryover"] + (1 if birdie else 0)
            game_data["running_points"][w] += total

            for p in game_data["players"]:
                if p != w:
                    game_data["running_points"][p] = max(0, game_data["running_points"][p] - 1)
                    if birdie and game_data["running_points"][p] > 0:
                        game_data["running_points"][p] -= 1

            game_data["hole_logs"].append(f"第 {hole+1} 洞：{w} 勝{' 🐦' if birdie else ''}（累積 {game_data['carryover']} 點）")
            game_data["carryover"] = 0
        else:
            game_data["hole_logs"].append(f"第 {hole+1} 洞：平手（累積中）")
            game_data["carryover"] += 1

        for p in game_data["players"]:
            game_data["scores"][p][str(hole)] = scores[p]
            pts = game_data["running_points"][p]
            game_data["current_titles"][p] = "💰 Super Rich" if pts >= 4 else ("💵 Rich" if pts > 0 else "")

        game_data["completed"] += 1
        save_game_to_drive(game_data, game_id)
        st.rerun()

# 🟩 END v3.3
