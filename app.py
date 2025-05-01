# Golf BANK v3.2 完整修正版
# 已修复所有缩进问题和缓存错误

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

# ================== 全局配置 ==================
BASE_URL = "https://your-streamlit-app-url/"  # 必须修改为实际部署地址
st.set_page_config(page_title="🏌️ Golf BANK v3.2", layout="wide")
st.title("🏌️ Golf BANK 系統")

# ================== 全局数据加载 ==================
@st.cache_data(
    ttl=3600,
    show_spinner="加载球场数据...",
    hash_funcs={"__main__": lambda _: "static"}
)
def load_course_db():
    try:
        file_mtime = os.path.getmtime("course_db.csv")
        df = pd.read_csv("course_db.csv")
        st.toast("✅ 球場資料加載成功", icon="⛳")
        return df
    except FileNotFoundError:
        st.error("❌ 錯誤：找不到 course_db.csv 文件")
        st.stop()

@st.cache_data(
    ttl=3600,
    show_spinner="加载球员名单..."
)
def load_players():
    try:
        df = pd.read_csv("players.csv")
        st.toast("✅ 球員名單加載成功", icon="👤")
        return df["name"].dropna().tolist()
    except FileNotFoundError:
        st.error("❌ 錯誤：找不到 players.csv 文件")
        st.stop()

course_df = load_course_db()
all_players = load_players()

# ================== Google Drive 整合 ==================
@st.cache_resource(show_spinner="連接Google雲端硬碟...")
def connect_drive():
    try:
        raw_secrets = st.secrets["gdrive"]
        secrets_dict = dict(raw_secrets)
        secrets_dict["private_key"] = secrets_dict["private_key"].replace("\\n", "\n")
        
        required_fields = ["type", "project_id", "private_key_id", 
                          "private_key", "client_email"]
        for field in required_fields:
            if field not in secrets_dict:
                raise ValueError(f"缺失必要字段: {field}")

        credentials = service_account.Credentials.from_service_account_info(
            secrets_dict,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build('drive', 'v3', credentials=credentials)
    except Exception as e:
        st.error(f"🔴 Google Drive 連接失敗: {str(e)}")
        st.stop()

drive_service = connect_drive()

@st.cache_resource
def create_or_get_folder():
    try:
        query = "mimeType='application/vnd.google-apps.folder' and name='GolfBank_Folder' and trashed=false"
        results = drive_service.files().list(
            q=query,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        items = results.get('files', [])
        return items[0]['id'] if items else drive_service.files().create(
            body={'name': 'GolfBank_Folder', 'mimeType': 'application/vnd.google-apps.folder'},
            fields='id',
            supportsAllDrives=True
        ).execute().get('id')
    except Exception as e:
        st.error(f"🔴 雲端資料夾操作失敗: {str(e)}")
        st.stop()

GAMES_FOLDER_ID = create_or_get_folder()

def save_game_to_drive(game_data, game_id):
    try:
        content = io.BytesIO(json.dumps(game_data, ensure_ascii=False, indent=2).encode("utf-8"))
        media = MediaIoBaseUpload(content, mimetype='application/json')
        
        query = f"name='game_{game_id}.json' and '{GAMES_FOLDER_ID}' in parents"
        existing_files = drive_service.files().list(
            q=query,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute().get('files', [])

        if existing_files:
            drive_service.files().update(
                fileId=existing_files[0]['id'],
                media_body=media,
                supportsAllDrives=True
            ).execute()
        else:
            drive_service.files().create(
                body={'name': f'game_{game_id}.json', 'parents': [GAMES_FOLDER_ID]},
                media_body=media,
                fields='id',
                supportsAllDrives=True
            ).execute()
        st.toast("💾 數據已保存到雲端", icon="☁️")
    except Exception as e:
        st.error(f"❌ 雲端保存失敗: {str(e)}")

def load_game_from_drive(game_id):
    try:
        query = f"name='game_{game_id}.json' and '{GAMES_FOLDER_ID}' in parents"
        result = drive_service.files().list(
            q=query,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        items = result.get('files', [])
        return json.loads(drive_service.files().get_media(fileId=items[0]['id']).execute()) if items else None
    except Exception as e:
        st.error(f"❌ 雲端加載失敗: {str(e)}")
        return None

# ================== 狀態管理 ==================
if "game_id" in st.query_params and not st.session_state.get("mode_initialized"):
    st.session_state.update({
        "mode": "查看端介面",
        "current_game_id": st.query_params["game_id"],
        "mode_initialized": True
    })
    st.rerun()

if "mode" not in st.session_state:
    st.session_state.mode = "選擇參賽球員"
if "current_game_id" not in st.session_state:
    st.session_state.current_game_id = ""

# ================== 模式路由控制（关键修正区域）==================
if st.session_state.mode == "查看端介面":
    st.header("📊 實時比賽數據查看端")
    game_id = st.session_state.current_game_id
    game_data = load_game_from_drive(game_id)
    
    if not game_data:
        st.error("⚠️ 找不到比賽資料")
        st.stop()
    
    with st.expander("比賽概況", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.subheader(f"比賽 ID: `{game_id}`")
        with col2:
            st.metric("當前進度", f"{game_data['completed']}/18 洞")
        with col3:
            st.metric("單注金額", f"${game_data['bet_per_person']}")
        st.write("參賽球員:", " | ".join(game_data["players"]))
    
    with st.expander("實時積分榜"):
        points_data = [{
            "球員": p,
            "當前積分": game_data["running_points"][p],
            "頭銜": game_data["current_titles"][p],
            "調整差點": game_data["handicaps"][p]
        } for p in game_data["players"]]
        st.dataframe(pd.DataFrame(points_data), use_container_width=True)
    
    with st.expander("逐洞記錄"):
        for idx, log in enumerate(game_data["hole_logs"], 1):
            st.code(f"第 {idx} 洞: {log}", language="markdown")
    
    if game_data["completed"] >= 18:
        st.success("🏁 比賽結束！最終結算")
        settlement_data = [{
            "球員": p,
            "淨積分": game_data["running_points"][p],
            "結算金額": game_data["running_points"][p] * game_data["bet_per_person"]
        } for p in game_data["players"]]
        st.dataframe(pd.DataFrame(settlement_data), use_container_width=True)

elif st.session_state.mode == "選擇參賽球員":
    st.header("👥 選擇參賽球員")
    selected_players = st.multiselect(
        "從名單中選擇",
        all_players,
        key="player_select",
        max_selections=4
    )
    
    col1, col2 = st.columns([0.3, 0.7])
    with col1:
        if st.button("✅ 確認名單", disabled=len(selected_players) < 2):
            st.session_state.selected_players = selected_players
            st.session_state.mode = "設定比賽資料"
            st.rerun()
    with col2:
        st.write("已選擇球員:", " | ".join(selected_players) if selected_players else "尚未選擇")

elif st.session_state.mode == "設定比賽資料":
    st.header("📋 比賽設定")
    players = st.session_state.selected_players
    
    with st.form("game_setup"):
        st.subheader("球員差點設定")
        cols = st.columns(len(players))
        handicaps = {}
        for idx, p in enumerate(players):
            with cols[idx]:
                handicaps[p] = st.number_input(
                    f"{p} 差點", 0, 54, 0, key=f"hdcp_{p}"
                )
        
        st.subheader("球場設定")
        selected_course = st.selectbox(
            "選擇球場",
            course_df["course_name"].unique(),
            index=0
        )
        
        areas_df = course_df[course_df["course_name"] == selected_course]
        valid_areas = areas_df.groupby("area").filter(lambda x: len(x) == 9)["area"].unique()
        
        col1, col2 = st.columns(2)
        with col1:
            front9_area = st.selectbox("前九洞區域", valid_areas)
        with col2:
            back9_area = st.selectbox("後九洞區域", [a for a in valid_areas if a != front9_area])
        
        front9 = areas_df[areas_df["area"] == front9_area].sort_values("hole")
        back9 = areas_df[areas_df["area"] == back9_area].sort_values("hole")
        
        bet_per_person = st.number_input(
            "單人賭金 (單位)",
            10, 1000, 100, 10
        )
        
        if st.form_submit_button("🚀 開始比賽"):
            today_str = datetime.now().strftime("%Y%m%d")
            existing = drive_service.files().list(
                q=f"name contains '{today_str}' and '{GAMES_FOLDER_ID}' in parents",
                supportsAllDrives=True
            ).execute().get('files', [])
            game_number = len([f for f in existing if f['name'].startswith(f"game_{today_str}_")]) + 1
            game_id = f"{today_str}_{game_number:02d}"
            
            game_data = {
                "game_id": game_id,
                "players": players,
                "handicaps": handicaps,
                "par": front9["par"].tolist() + back9["par"].tolist(),
                "hcp": front9["hcp"].tolist() + back9["hcp"].tolist(),
                "bet_per_person": bet_per_person,
                "scores": {p: {} for p in players},
                "running_points": {p: 0 for p in players},
                "current_titles": {p: "" for p in players},
                "hole_logs": [],
                "completed": 0
            }
            
            save_game_to_drive(game_data, game_id)
            st.session_state.current_game_id = game_id
            st.session_state.mode = "主控端成績輸入"
            st.rerun()

elif st.session_state.mode == "主控端成績輸入":
    game_id = st.session_state.current_game_id
    game_data = load_game_from_drive(game_id)
    
    if not game_data:
        st.error("❌ 比賽資料異常")
        st.stop()
    
    col1, col2 = st.columns([0.7, 0.3])
    with col1:
        st.header(f"⛳ 成績輸入 - {game_id}")
    with col2:
        qr = qrcode.make(f"{BASE_URL}?game_id={game_id}")
        buf = BytesIO()
        qr.save(buf)
        st.image(buf.getvalue(), caption="查看端二維碼")
    
    for hole in range(18):
        st.divider()
        current_par = game_data["par"][hole]
        current_hcp = game_data["hcp"][hole]
        
        st.markdown(f"### 第 {hole+1} 洞 (Par {current_par} | HCP {current_hcp})")
        
        cols = st.columns(len(game_data["players"]))
        scores = {}
        for idx, player in enumerate(game_data["players"]):
            with cols[idx]:
                default = game_data["scores"][player].get(str(hole), current_par)
                scores[player] = st.number_input(
                    f"{player} 桿數", 1, 15, default, key=f"hole_{hole}_{player}"
                )
        
        confirmed = st.session_state.get(f"hole_{hole}_confirmed", False)
        if not confirmed and st.button(f"✅ 確認第 {hole+1} 洞成績", key=f"confirm_{hole}"):
            adjusted = {}
            for p in game_data["players"]:
                adjust = sum(
                    1 for q in game_data["players"]
                    if p != q and 
                    (game_data["handicaps"][q] - game_data["handicaps"][p]) > 0 and 
                    current_hcp <= (game_data["handicaps"][q] - game_data["handicaps"][p])
                )
                adjusted[p] = scores[p] - adjust
            
            victory = {p: sum(1 for q in game_data["players"] if p != q and adjusted[p] < adjusted[q]) 
                      for p in game_data["players"]}
            winners = [p for p, wins in victory.items() if wins == len(game_data["players"])-1]
            
            if len(winners) == 1:
                winner = winners[0]
                birdie = scores[winner] <= (current_par - 1)
                game_data["running_points"][winner] += 1 + (1 if birdie else 0)
                
                for p in game_data["players"]:
                    if p != winner:
                        game_data["running_points"][p] = max(0, game_data["running_points"][p] - 1)
                
                log_msg = f"第 {hole+1} 洞：{winner} 勝出{' 🐦' if birdie else ''}"
            else:
                log_msg = f"第 {hole+1} 洞：平手"
            
            for p in game_data["players"]:
                game_data["scores"][p][str(hole)] = scores[p]
            
            game_data["hole_logs"].append(log_msg)
            game_data["completed"] = hole + 1
            
            for p in game_data["players"]:
                pts = game_data["running_points"][p]
                game_data["current_titles"][p] = (
                    "💰 Super Rich" if pts >= 4 else
                    "💵 Rich" if pts > 0 else ""
                )
            
            save_game_to_drive(game_data, game_id)
            st.session_state[f"hole_{hole}_confirmed"] = True
            st.rerun()
        
        if confirmed:
            st.info(f"📝 已確認: {game_data['hole_logs'][hole]}")

else:
    st.warning("⚠️ 系統狀態異常，正在重置...")
    time.sleep(2)
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# ================== 系統維護面板 ==================
with st.sidebar.expander("🔧 系統維護"):
    col1, col2 = st.columns(2)
    with col1:
        if st.button("♻️ 清除前端緩存"):
            st.cache_data.clear()
            st.success("前端緩存已清除")
    with col2:
        if st.button("🔄 重設所有狀態"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    
    st.write("### 數據版本信息")
    st.metric("球場數據版本", datetime.fromtimestamp(os.path.getmtime("course_db.csv")).strftime("%Y-%m-%d %H:%M"))
    st.metric("球員數據版本", datetime.fromtimestamp(os.path.getmtime("players.csv")).strftime("%Y-%m-%d %H:%M"))

# ================== 頁尾聲明 ==================
st.divider()
st.caption(f"Golf BANK v3.2 | 高爾夫球局管理系統 | 數據最後更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
