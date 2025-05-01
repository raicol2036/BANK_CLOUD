# Golf BANK v3.2 完整修正版
# 包含Google Drive整合、多模式界面和完整錯誤處理

import streamlit as st
import pandas as pd
import json
import qrcode
import io
import time
from io import BytesIO
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ================== 全局配置 ==================
BASE_URL = "https://your-streamlit-app-url/"  # 必須修改為實際部署地址
st.set_page_config(page_title="🏌️ Golf BANK v3.2", layout="wide")
st.title("🏌️ Golf BANK 系統")

# ================== 全局数据加载 ==================
@st.cache_data
def load_course_db():
    try:
        df = pd.read_csv("course_db.csv")
        st.toast("✅ 球場資料加載成功", icon="⛳")
        return df
    except Exception as e:
        st.error(f"❌ 無法加載球場資料: {str(e)}")
        st.stop()

@st.cache_data
def load_players():
    try:
        df = pd.read_csv("players.csv")
        st.toast("✅ 球員名單加載成功", icon="👤")
        return df["name"].dropna().tolist()
    except Exception as e:
        st.error(f"❌ 無法加載球員名單: {str(e)}")
        st.stop()

# 預加載基礎數據
course_df = load_course_db()
all_players = load_players()

# ================== Google Drive 整合 ==================
@st.cache_resource
def connect_drive():
    try:
        raw_secrets = st.secrets["gdrive"]
        secrets_dict = dict(raw_secrets)
        
        # 處理換行符問題
        secrets_dict["private_key"] = secrets_dict["private_key"].replace("\\n", "\n")
        
        # 驗證必要字段
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
        results = drive_service.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        items = results.get('files', [])
        
        if items:
            return items[0]['id']
        else:
            file_metadata = {
                'name': 'GolfBank_Folder',
                'mimeType': 'application/vnd.google-apps.folder'
            }
            file = drive_service.files().create(
                body=file_metadata, 
                fields='id',
                supportsAllDrives=True
            ).execute()
            return file.get('id')
    except Exception as e:
        st.error(f"🔴 無法建立雲端資料夾: {str(e)}")
        st.stop()

GAMES_FOLDER_ID = create_or_get_folder()

def save_game_to_drive(game_data, game_id):
    try:
        file_metadata = {'name': f'game_{game_id}.json', 'parents': [GAMES_FOLDER_ID]}
        content = io.BytesIO(json.dumps(game_data, ensure_ascii=False, indent=2).encode("utf-8"))
        media = MediaIoBaseUpload(content, mimetype='application/json')

        # 檢查是否已存在
        query = f"name='game_{game_id}.json' and '{GAMES_FOLDER_ID}' in parents and trashed=false"
        result = drive_service.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        items = result.get('files', [])

        if items:
            # 更新現有文件
            file_id = items[0]['id']
            drive_service.files().update(
                fileId=file_id,
                media_body=media,
                supportsAllDrives=True
            ).execute()
        else:
            # 新建文件
            drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id',
                supportsAllDrives=True
            ).execute()
        st.toast("💾 比賽數據已保存到雲端", icon="☁️")
    except Exception as e:
        st.error(f"❌ 保存失敗: {str(e)}")

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
        st.error(f"❌ 加載失敗: {str(e)}")
        return None

# ================== 狀態管理 ==================
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

# ================== 查看端界面 ==================
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
        points_data = []
        for p in game_data["players"]:
            points_data.append({
                "球員": p,
                "當前積分": game_data["running_points"][p],
                "頭銜": game_data["current_titles"][p],
                "調整差點": game_data["handicaps"][p]
            })
        st.dataframe(pd.DataFrame(points_data), use_container_width=True)
    
    with st.expander("逐洞記錄"):
        for idx, log in enumerate(game_data["hole_logs"], 1):
            st.code(f"第 {idx} 洞: {log}", language="markdown")
    
    if game_data["completed"] >= 18:
        st.success("🏁 比賽結束！最終結算")
        total_bet = game_data["bet_per_person"] * len(game_data["players"])
        settlement_data = []
        for p in game_data["players"]:
            settlement_data.append({
                "球員": p,
                "淨積分": game_data["running_points"][p],
                "結算金額": game_data["running_points"][p] * game_data["bet_per_person"]
            })
        st.dataframe(pd.DataFrame(settlement_data), use_container_width=True)

# ================== 主控端：選擇球員 ==================
elif st.session_state.mode == "選擇參賽球員":
    st.header("👥 選擇參賽球員")
    st.caption("最多選擇4位球員")
    
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

# ================== 主控端：比賽設定 ==================
elif st.session_state.mode == "設定比賽資料":
    st.header("📋 比賽設定")
    players = st.session_state.selected_players
    
    with st.form("game_setup"):
        # 球員差點設定
        st.subheader("球員差點設定")
        handicaps = {}
        cols = st.columns(len(players))
        for idx, p in enumerate(players):
            with cols[idx]:
                handicaps[p] = st.number_input(
                    f"{p} 差點",
                    min_value=0,
                    max_value=54,
                    value=0,
                    key=f"hdcp_{p}"
                )
        
        # 球場設定
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
        
        # 賭金設定
        bet_per_person = st.number_input(
            "單人賭金 (單位)",
            min_value=10,
            max_value=1000,
            value=100,
            step=10
        )
        
        if st.form_submit_button("🚀 開始比賽"):
            # 生成比賽ID
            today_str = datetime.now().strftime("%Y%m%d")
            query = f"name contains '{today_str}' and '{GAMES_FOLDER_ID}' in parents"
            existing = drive_service.files().list(q=query, supportsAllDrives=True).execute().get('files', [])
            game_number = len([f for f in existing if f['name'].startswith(f"game_{today_str}_")]) + 1
            game_id = f"{today_str}_{game_number:02d}"
            
            # 初始化比賽數據
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

# ================== 主控端：成績輸入 ==================
elif st.session_state.mode == "主控端成績輸入":
    game_id = st.session_state.current_game_id
    game_data = load_game_from_drive(game_id)
    
    if not game_data:
        st.error("❌ 比賽資料異常")
        st.stop()
    
    # 界面佈局
    col1, col2 = st.columns([0.7, 0.3])
    with col1:
        st.header(f"⛳ 成績輸入 - {game_id}")
    with col2:
        qr = qrcode.make(f"{BASE_URL}?game_id={game_id}")
        buf = BytesIO()
        qr.save(buf)
        st.image(buf.getvalue(), caption="查看端二維碼")
    
    # 逐洞輸入
    for hole in range(18):
        st.divider()
        current_par = game_data["par"][hole]
        current_hcp = game_data["hcp"][hole]
        
        st.markdown(f"### 第 {hole+1} 洞 (Par {current_par} | HCP {current_hcp})")
        
        # 球員成績輸入
        cols = st.columns(len(game_data["players"]))
        scores = {}
        for idx, player in enumerate(game_data["players"]):
            with cols[idx]:
                default = game_data["scores"][player].get(str(hole), current_par)
                scores[player] = st.number_input(
                    f"{player} 桿數",
                    min_value=1,
                    max_value=15,
                    value=default,
                    key=f"hole_{hole}_{player}"
                )
        
        # 確認按鈕邏輯
        confirmed = st.session_state.get(f"hole_{hole}_confirmed", False)
        if not confirmed and st.button(f"✅ 確認第 {hole+1} 洞成績", key=f"confirm_{hole}"):
            # 計算調整桿數
            adjusted = {}
            for p in game_data["players"]:
                adjust = 0
                for q in game_data["players"]:
                    if p == q:
                        continue
                    diff = game_data["handicaps"][q] - game_data["handicaps"][p]
                    if diff > 0 and current_hcp <= diff:
                        adjust += 1
                adjusted[p] = scores[p] - adjust
            
            # 判定勝負
            victory = {p: 0 for p in game_data["players"]}
            for p in game_data["players"]:
                for q in game_data["players"]:
                    if p != q and adjusted[p] < adjusted[q]:
                        victory[p] += 1
            
            winners = [p for p, wins in victory.items() if wins == len(game_data["players"])-1]
            
            # 更新積分
            if len(winners) == 1:
                winner = winners[0]
                birdie = scores[winner] <= (current_par - 1)
                game_data["running_points"][winner] += 1 + (1 if birdie else 0)
                
                for p in game_data["players"]:
                    if p != winner:
                        game_data["running_points"][p] = max(0, game_data["running_points"][p] - 1)
                
                log_msg = f"第 {hole+1} 洞：{winner} 勝出"
                if birdie:
                    log_msg += " 🐦"
            else:
                log_msg = f"第 {hole+1} 洞：平手"
            
            # 更新數據
            for p in game_data["players"]:
                game_data["scores"][p][str(hole)] = scores[p]
            
            game_data["hole_logs"].append(log_msg)
            game_data["completed"] = hole + 1
            
            # 更新頭銜
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

# ================== 調試面板 ==================
with st.sidebar.expander("🛠️ 系統狀態"):
    st.write("當前模式:", st.session_state.mode)
    st.write("比賽ID:", st.session_state.get("current_game_id", "N/A"))
    st.write("球場資料版本:", course_df["course_name"].unique()[0])
    st.write("已加載球員數:", len(all_players))
    
    if st.button("🔄 重設系統"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# ================== 頁尾 ==================
st.divider()
st.caption("Golf BANK v3.2 | 高爾夫球局管理系統 | 技術支援: support@golfbank.tw")
