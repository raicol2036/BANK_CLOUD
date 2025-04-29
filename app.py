import streamlit as st
import pandas as pd
import json
import uuid
import qrcode
from io import BytesIO
from google.oauth2 import service_account
from googleapiclient.discovery import build

BASE_URL = "https://bankcloud-ctk4bhakw7fro8k3wmpava.streamlit.app/"

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
    from googleapiclient.http import MediaInMemoryUpload
    file_metadata = {'name': f'game_{game_id}.json', 'parents': [GAMES_FOLDER_ID]}
    media = MediaInMemoryUpload(json.dumps(game_data, ensure_ascii=False, indent=2).encode(), mimetype='application/json')
    drive_service.files().create(body=file_metadata, media_body=media, fields='id', supportsAllDrives=True).execute()

def load_game_from_drive(game_id):
    query = f"name='game_{game_id}.json' and '{GAMES_FOLDER_ID}' in parents and trashed=false"
    result = drive_service.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    items = result.get('files', [])
    if not items:
        return None
    file_id = items[0]['id']
    file = drive_service.files().get_media(fileId=file_id).execute()
    return json.loads(file)

def generate_qr(url):
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf)
    return buf

st.set_page_config(page_title="🏌️ Golf BANK v3.1", layout="wide")
st.title("🏌️ Golf BANK 系統")

if "mode" not in st.session_state:
    st.session_state.mode = None
if "current_game_id" not in st.session_state:
    st.session_state.current_game_id = ""
if "point_bank" not in st.session_state:
    st.session_state.point_bank = 1

@st.cache_data
def load_course_db():
    return pd.read_csv("course_db.csv")

@st.cache_data
def load_players():
    df = pd.read_csv("players.csv")
    return df["name"].dropna().tolist()

course_df = load_course_db()
player_names = load_players()

params = st.query_params
if "game_id" in params:
    game_id_param = params["game_id"][0]
    st.session_state.mode = "隊員查看比賽"
    st.session_state.current_game_id = game_id_param

if st.session_state.mode:
    mode = st.session_state.mode
else:
    mode = st.sidebar.radio("選擇模式", ["建立新比賽", "主控端成績輸入", "隊員查看比賽", "歷史紀錄管理"])

if mode == "建立新比賽":
    game_id = str(uuid.uuid4())[:8]
    st.success(f"✅ 新比賽ID：{game_id}")

    selected_course = st.selectbox("選擇球場名稱", course_df["course_name"].unique())

    # 找出該球場所有區域中，剛好9筆資料的
    areas_df = course_df[course_df["course_name"] == selected_course]
    valid_areas = (
        areas_df.groupby("area")
        .filter(lambda df: len(df) == 9)["area"]
        .unique()
    )

    if len(valid_areas) < 2:
        st.warning("⚠️ 此球場沒有兩組完整的9洞區域，請檢查資料")
        st.stop()

    area_front9 = st.selectbox("選擇前九洞區域", valid_areas, key="front9")
    area_back9 = st.selectbox("選擇後九洞區域", valid_areas, key="back9")

    front9 = areas_df[areas_df["area"] == area_front9].sort_values("hole")
    back9 = areas_df[areas_df["area"] == area_back9].sort_values("hole")

    if len(front9) != 9 or len(back9) != 9:
        st.error("⚠️ 選擇的區域不是完整9洞，請確認 course_db.csv 資料正確")
        st.stop()

    par = front9["par"].tolist() + back9["par"].tolist()
    hcp = front9["hcp"].tolist() + back9["hcp"].tolist()

    st.markdown("**球員差點設定：**")
    handicaps = {p: st.number_input(f"{p} 差點", 0, 54, 0) for p in player_names}
    bet_per_person = st.number_input("單人賭金", 10, 1000, 100)

    if st.button("✅ 建立比賽"):
        game_data = {
            "game_id": game_id,
            "players": player_names,
            "handicaps": handicaps,
            "par": par,
            "hcp": hcp,
            "bet_per_person": bet_per_person,
            "scores": {p: {str(i): par[i] for i in range(18)} for p in player_names},
            "events": {},
            "running_points": {p: 0 for p in player_names},
            "current_titles": {p: "" for p in player_names},
            "hole_logs": [],
            "completed": 0
        }
        save_game_to_drive(game_data, game_id)
        st.session_state.mode = "主控端成績輸入"
        st.session_state.current_game_id = game_id
        st.rerun()

st.caption("Golf BANK v3.1 System © 2024")
