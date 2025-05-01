# Golf BANK v3.2 完整修正版
# 已修复缩进错误并优化移动端兼容性

import streamlit as st
import pandas as pd
import json
import uuid
import qrcode
import io
from io import BytesIO
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

BASE_URL = "https://your-streamlit-app-url/"  # 必須修改為實際部署地址

st.set_page_config(page_title="🏌️ Golf BANK v3.2", layout="wide")
st.title("🏌️ Golf BANK 系統")

# --- Google Drive 連接函數 ---
@st.cache_resource
def connect_drive():
    raw_secrets = st.secrets["gdrive"]
    secrets_dict = dict(raw_secrets)
    secrets_dict["private_key"] = secrets_dict["private_key"].replace("\\n", "\n")
    credentials = service_account.Credentials.from_service_account_info(
        secrets_dict,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build('drive', 'v3', credentials=credentials)

drive_service = connect_drive()

# --- 核心數據操作函數 ---
@st.cache_resource
def create_or_get_folder():
    query = "mimeType='application/vnd.google-apps.folder' and name='GolfBank_Folder' and trashed=false"
    results = drive_service.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    items = results.get('files', [])
    if items:
        return items[0]['id']
    else:
        file_metadata = {
            'name': 'GolfBank_Folder',
            'mimeType': 'application/vnd.google-apps.folder'
        }
        file = drive_service.files().create(body=file_metadata, fields='id', supportsAllDrives=True).execute()
        return file.get('id')

GAMES_FOLDER_ID = create_or_get_folder()

def save_game_to_drive(game_data, game_id):
    try:
        file_metadata = {'name': f'game_{game_id}.json', 'parents': [GAMES_FOLDER_ID]}
        content = io.BytesIO(json.dumps(game_data, ensure_ascii=False, indent=2).encode("utf-8"))
        media = MediaIoBaseUpload(content, mimetype='application/json')

        query = f"name='game_{game_id}.json' and '{GAMES_FOLDER_ID}' in parents and trashed=false"
        result = drive_service.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        items = result.get('files', [])

        if items:
            file_id = items[0]['id']
            drive_service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else:
            drive_service.files().create(body=file_metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
    except Exception as e:
        st.error(f"保存數據失敗: {str(e)}")

def load_game_from_drive(game_id):
    try:
        query = f"name='game_{game_id}.json' and '{GAMES_FOLDER_ID}' in parents and trashed=false"
        result = drive_service.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        items = result.get('files', [])
        if not items:
            return None
        file_id = items[0]['id']
        file = drive_service.files().get_media(fileId=file_id).execute()
        return json.loads(file)
    except Exception as e:
        st.error(f"加載數據失敗: {str(e)}")
        return None

# --- 模式自動切換邏輯 ---
query_params = st.query_params
if "game_id" in query_params and not st.session_state.get("mode_initialized"):
    st.session_state.mode = "查看端介面"
    st.session_state.current_game_id = query_params["game_id"]
    st.session_state.mode_initialized = True
    st.rerun()

if "mode" not in st.session_state:
    st.session_state.mode = "選擇參賽球員"
if "current_game_id" not in st.session_state:
    st.session_state.current_game_id = ""

# === 查看端界面 ===
if st.session_state.mode == "查看端介面":
    st.header("📊 實時比賽數據查看端")
    game_id = st.session_state.current_game_id
    game_data = load_game_from_drive(game_id)
    
    if not game_data:
        st.error("比賽不存在或數據加載失敗")
        st.stop()
    
    with st.expander("比賽基本信息", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.subheader(f"比賽ID: `{game_id}`")
        with col2:
            st.metric("當前進度", f"{game_data['completed']}/18洞")
        with col3:
            st.metric("單注金額", f"${game_data['bet_per_person']}")

        st.write("參賽球員:", ", ".join(game_data["players"]))
    
    with st.expander("實時積分看板", expanded=True):
        points_data = []
        for p in game_data["players"]:
            points_data.append({
                "球員": p,
                "當前積分": game_data["running_points"][p],
                "頭銜": game_data["current_titles"][p],
                "調整差點": game_data["handicaps"][p]
            })
        points_df = pd.DataFrame(points_data)
        st.dataframe(points_df, use_container_width=True, hide_index=True)
    
    with st.expander("逐洞比賽記錄"):
        for idx, log in enumerate(game_data["hole_logs"], 1):
            st.write(f"{idx}. {log}")
    
    if game_data["completed"] >= 18:
        st.success("🏁 比賽已結束！最終結算結果")
        total_bet = game_data["bet_per_person"] * len(game_data["players"])
        final_points = {p: game_data["running_points"][p] for p in game_data["players"]}
        
        # 計算輸贏金額
        payouts = {}
        for p in game_data["players"]:
            payouts[p] = final_points[p] * game_data["bet_per_person"]
        
        # 顯示結算表格
        settlement_df = pd.DataFrame({
            "球員": payouts.keys(),
            "淨賺點數": final_points.values(),
            "結算金額": [f"${val}" for val in payouts.values()]
        })
        st.dataframe(settlement_df, use_container_width=True)

# === 主控端：選擇球員 ===
elif st.session_state.mode == "選擇參賽球員":
    st.header("👥 選擇參賽球員（最多4位）")
    
    @st.cache_data
    def load_course_db():
        return pd.read_csv("course_db.csv")

    @st.cache_data
    def load_players():
        df = pd.read_csv("players.csv")
        return df["name"].dropna().tolist()

    course_df = load_course_db()
    all_players = load_players()
    
    player_names = st.multiselect("選擇球員", all_players, key="player_select")
    if len(player_names) > 4:
        st.error("⚠️ 最多只能選擇4位球員參賽")
    elif len(player_names) == 4:
        st.success("✅ 已選擇4位球員")
        st.session_state.selected_players = player_names
        st.session_state.mode = "設定比賽資料"
        st.rerun()

# === 主控端：設定比賽資料 ===
elif st.session_state.mode == "設定比賽資料":
    st.header("📋 比賽設定")

    player_names = st.session_state.selected_players
    handicaps = {p: st.number_input(f"{p} 差點", 0, 54, 0, key=f"hdcp_{p}") for p in player_names}

    selected_course = st.selectbox("選擇球場名稱", course_df["course_name"].unique())
    areas_df = course_df[course_df["course_name"] == selected_course]
    valid_areas = (
        areas_df.groupby("area")
        .filter(lambda df: len(df) == 9)["area"]
        .unique()
    )

    area_front9 = st.selectbox("前九洞區域", valid_areas, key="front9")
    area_back9 = st.selectbox("後九洞區域", valid_areas, key="back9")

    front9 = areas_df[areas_df["area"] == area_front9].sort_values("hole")
    back9 = areas_df[areas_df["area"] == area_back9].sort_values("hole")

    if len(front9) != 9 or len(back9) != 9:
        st.error("⚠️ 選擇的區域不是完整9洞，請確認資料正確")
        st.stop()

    par = front9["par"].tolist() + back9["par"].tolist()
    hcp = front9["hcp"].tolist() + back9["hcp"].tolist()
    bet_per_person = st.number_input("單人賭金", 10, 1000, 100)

    def generate_game_id():
        today_str = datetime.now().strftime("%Y%m%d")
        query = f"name contains '{today_str}' and '{GAMES_FOLDER_ID}' in parents and trashed=false"
        result = drive_service.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        items = result.get('files', [])
        used_numbers = []
        for item in items:
            name = item['name']
            if name.startswith(f"game_{today_str}_"):
                try:
                    suffix = int(name.split("_")[-1].split(".")[0])
                    used_numbers.append(suffix)
                except:
                    continue
        next_number = max(used_numbers, default=0) + 1
        return f"{today_str}_{str(next_number).zfill(2)}"

    if st.button("✅ 開始球局"):
        game_id = generate_game_id()
        game_data = {
            "game_id": game_id,
            "players": player_names,
            "handicaps": handicaps,
            "par": par,
            "hcp": hcp,
            "bet_per_person": bet_per_person,
            "scores": {p: {} for p in player_names},
            "events": {},
            "running_points": {p: 0 for p in player_names},
            "current_titles": {p: "" for p in player_names},
            "hole_logs": [],
            "completed": 0
        }
        save_game_to_drive(game_data, game_id)
        st.session_state.current_game_id = game_id
        st.session_state.mode = "主控端成績輸入"
        st.rerun()

# === 主控端：多洞成績輸入 + 比對勝負 ===
elif st.session_state.mode == "主控端成績輸入":
    game_id = st.session_state.current_game_id
    game_data = load_game_from_drive(game_id)

    if not game_data:
        st.error("⚠️ 找不到該比賽資料")
        st.stop()

    col_left, col_right = st.columns([0.75, 0.25])
    with col_left:
        st.header("⛳ 主控端輸入介面")
    with col_right:
        qr_url = f"{BASE_URL}?game_id={game_id}"
        img = qrcode.make(qr_url)
        buf = BytesIO()
        img.save(buf)
        st.image(buf.getvalue(), use_container_width=True)

    players = game_data["players"]
    par_list = game_data["par"]
    hcp_list = game_data["hcp"]
    hdcp = game_data["handicaps"]

    for hole in range(18):
        par = par_list[hole]
        hcp = hcp_list[hole]
        st.markdown(f"### 第 {hole + 1} 洞 (Par {par} / HCP {hcp})")

        cols = st.columns(len(players))
        scores = {}
        for idx, p in enumerate(players):
            with cols[idx]:
                st.markdown(f"**{p} 押數（{game_data['running_points'].get(p, 0)} 點）**")
                default_score = game_data["scores"].get(p, {}).get(str(hole), par)
                scores[p] = st.number_input(
                    f"{p}", 1, 15, value=default_score, key=f"score_{p}_{hole}_input"
                )

        confirmed_key = f"hole_{hole}_confirmed"
        if confirmed_key not in st.session_state:
            st.session_state[confirmed_key] = hole < game_data["completed"]

        if not st.session_state[confirmed_key]:
            if st.button(f"✅ 確認第 {hole + 1} 洞成績", key=f"confirm_btn_{hole}"):
                scores_raw = {p: scores[p] for p in players}
                adjusted_scores = {}
                
                # 修復後的積分計算區塊
                for p in players:
                    total_adjust = 0
                    for q in players:
                        if p == q:
                            continue
                        diff = hdcp[q] - hdcp[p]
                        if diff > 0 and hcp <= diff:
                            total_adjust += 1
                    adjusted_scores[p] = scores[p] - total_adjust

                victory_map = {}
                for p in players:
                    wins = 0
                    for q in players:
                        if p == q:
                            continue
                        if adjusted_scores[p] < adjusted_scores[q]:
                            wins += 1
                    victory_map[p] = wins

                winners = [p for p in players if victory_map[p] == len(players) - 1]
                log = f"Hole {hole + 1}: "

                if len(winners) == 1:
                    winner = winners[0]
                    is_birdy = scores_raw[winner] <= (par - 1)
                    birdy_bonus = 1 if is_birdy else 0
                    game_data["running_points"][winner] += 1 + birdy_bonus
                    for p in players:
                        if p != winner:
                            game_data["running_points"][p] = max(0, game_data["running_points"][p] - 1)  # 修復扣分邏輯
                    log += f"🏆 {winner} 勝出 {'🐦' if is_birdy else ''}"
                else:
                    log += "⚖️ 平手"

                for p in players:
                    game_data["scores"].setdefault(p, {})[str(hole)] = scores[p]

                game_data["hole_logs"].append(log)
                game_data["completed"] = max(game_data["completed"], hole + 1)

                for p in players:
                    pt = game_data["running_points"][p]
                    if pt >= 4:
                        game_data["current_titles"][p] = "Super Rich"
                    elif pt > 0:
                        game_data["current_titles"][p] = "Rich"
                    else:
                        game_data["current_titles"][p] = ""

                save_game_to_drive(game_data, game_id)
                st.session_state[confirmed_key] = True
                st.rerun()
        else:
            last_log = game_data["hole_logs"][hole] if hole < len(game_data["hole_logs"]) else "✅ 已確認"
            st.markdown(f"📝 {last_log}")
        st.divider()

    if game_data["completed"] >= 18:
        st.success("🏁 比賽已完成！")
