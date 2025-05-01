# Golf BANK v3.2 修复版
# 新增查看端界面/积分逻辑修正/结算功能

import streamlit as st
import pandas as pd
import json
import qrcode
import io
from io import BytesIO
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# !!! 重要：修改为你的Streamlit应用实际部署地址 !!!
BASE_URL = "https://your-streamlit-app-url/"  # 必须修改否则QR码无法使用

st.set_page_config(page_title="🏌️ Golf BANK v3.2", layout="wide")
st.title("🏌️ Golf BANK 系統")

if BASE_URL == "https://your-streamlit-app-url/":
    st.warning("⚠️ 请先配置BASE_URL为你的Streamlit应用地址！")

# --- Google Drive 连接函数 ---
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

# --- 核心数据操作函数 ---
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
        st.error(f"保存数据失败: {str(e)}")

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
        st.error(f"加载数据失败: {str(e)}")
        return None

# --- 模式自动切换逻辑 ---
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

# --- 查看端界面 ---
if st.session_state.mode == "查看端介面":
    st.header("📊 实时比赛数据查看端")
    game_id = st.session_state.current_game_id
    game_data = load_game_from_drive(game_id)
    
    if not game_data:
        st.error("比赛不存在或数据加载失败")
        st.stop()
    
    with st.expander("比赛基本信息", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.subheader(f"比赛ID: `{game_id}`")
        with col2:
            st.metric("当前进度", f"{game_data['completed']}/18洞")
        with col3:
            st.metric("单注金额", f"${game_data['bet_per_person']}")

        st.write("参赛球员:", ", ".join(game_data["players"]))
    
    with st.expander("实时积分看板", expanded=True):
        points_data = []
        for p in game_data["players"]:
            points_data.append({
                "球员": p,
                "当前积分": game_data["running_points"][p],
                "头衔": game_data["current_titles"][p],
                "调整差点": game_data["handicaps"][p]
            })
        points_df = pd.DataFrame(points_data)
        st.dataframe(points_df, use_container_width=True, hide_index=True)
    
    with st.expander("逐洞比赛记录"):
        for idx, log in enumerate(game_data["hole_logs"], 1):
            st.write(f"{idx}. {log}")
    
    if game_data["completed"] >= 18:
        st.success("🏁 比赛已结束！最终结算结果")
        total_bet = game_data["bet_per_person"] * len(game_data["players"])
        final_points = {p: game_data["running_points"][p] for p in game_data["players"]}
        
        # 计算输赢金额
        payouts = {}
        for p in game_data["players"]:
            payouts[p] = final_points[p] * game_data["bet_per_person"]
        
        # 显示结算表格
        settlement_df = pd.DataFrame({
            "球员": payouts.keys(),
            "净赚点数": final_points.values(),
            "结算金额": [f"${val}" for val in payouts.values()]
        })
        st.dataframe(settlement_df, use_container_width=True)

# --- 主控端其他模式逻辑（保持原样，仅修改积分扣减部分）---
# ... [保持原有模式逻辑不变，仅修改以下部分] ...

                # 修正后的积分逻辑
                for p in players:
                    if p != winner:
                        # 允许扣到0分，不低于0
                        game_data["running_points"][p] = max(0, game_data["running_points"][p] - 1)

# ... [其余主控端代码保持不变] ...
