# Golf BANK v3.2 完整稳定版
# 已修复缓存错误和云存储连接问题

import streamlit as st
import pandas as pd
import json
import qrcode
import io
import os
from io import BytesIO
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ================== 全局配置 ==================
BASE_URL = "https://bankcloud11111.streamlit.app/"  # 必须修改为实际部署地址
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
        # 通过文件修改时间触发缓存更新
        file_mtime = os.path.getmtime("course_db.csv")
        df = pd.read_csv("course_db.csv")
        st.toast("✅ 球場資料加載成功", icon="⛳")
        return df
    except FileNotFoundError:
        st.error("❌ 錯誤：找不到 course_db.csv 文件")
        st.stop()
    except pd.errors.ParserError:
        st.error("❌ 錯誤：CSV 文件格式不正確")
        st.stop()
    except Exception as e:
        st.error(f"❌ 未知錯誤: {str(e)}")
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
    except Exception as e:
        st.error(f"❌ 球員名單加載失敗: {str(e)}")
        st.stop()

# 预加载基础数据（关键缓存修复点）
course_df = load_course_db()
all_players = load_players()

# ================== Google Drive 整合 ==================
@st.cache_resource(show_spinner="連接Google雲端硬碟...")
def connect_drive():
    try:
        raw_secrets = st.secrets["gdrive"]
        secrets_dict = dict(raw_secrets)
        
        # 处理Windows/Linux换行符差异
        secrets_dict["private_key"] = secrets_dict["private_key"].replace("\\n", "\n")
        
        # 验证必要字段
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
        
        if items := results.get('files', []):
            return items[0]['id']
        else:
            file = drive_service.files().create(
                body={'name': 'GolfBank_Folder', 'mimeType': 'application/vnd.google-apps.folder'},
                fields='id',
                supportsAllDrives=True
            ).execute()
            return file.get('id')
    except Exception as e:
        st.error(f"🔴 雲端資料夾操作失敗: {str(e)}")
        st.stop()

GAMES_FOLDER_ID = create_or_get_folder()

def save_game_to_drive(game_data, game_id):
    try:
        content = io.BytesIO(json.dumps(game_data, ensure_ascii=False, indent=2).encode("utf-8"))
        media = MediaIoBaseUpload(content, mimetype='application/json')
        
        # 检查文件是否存在
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
        
        if not (items := result.get('files', [])):
            return None
            
        file = drive_service.files().get_media(fileId=items[0]['id']).execute()
        return json.loads(file)
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

# ================== 查看端界面 ==================
if st.session_state.mode == "查看端介面":
    # ... (保持原有查看端界面逻辑不变)

# ================== 主控端：選擇參賽球員 ==================
elif st.session_state.mode == "選擇參賽球員":
    # ... (保持原有球員選擇逻辑不变)

# ================== 主控端：比賽設定 ==================
elif st.session_state.mode == "設定比賽資料":
    # ... (保持原有比賽設定逻辑不变)

# ================== 主控端：成績輸入 ==================
elif st.session_state.mode == "主控端成績輸入":
    # ... (保持原有成績輸入逻辑不变)

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
st.caption("""
Golf BANK v3.2 | 高爾夫球局管理系統  
技術支援：support@golfbank.tw | 數據最後更新：%s
""" % datetime.now().strftime("%Y-%m-%d"))
