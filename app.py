
import streamlit as st
import pandas as pd
import json
import uuid
import qrcode
import io
from io import BytesIO
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

BASE_URL = "https://bankcloud-ctk4bhakw7fro8k3wmpava.streamlit.app/"

st.set_page_config(page_title="🏌️ Golf BANK v3.3", layout="wide")
st.title("🏌️ Golf BANK 系統")

@st.cache_resource
def connect_drive():
    raw_secrets = st.secrets["gdrive"]
    secrets_dict = dict(raw_secrets)
    secrets_dict["private_key"] = secrets_dict["private_key"].replace("\n", "\n")
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

@st.cache_data
def load_course_db():
    return pd.read_csv("course_db.csv")

@st.cache_data
def load_players():
    df = pd.read_csv("players.csv")
    return df["name"].dropna().tolist()

# 🔰 首頁：開始新比賽
if "mode" not in st.session_state:
    st.session_state.mode = "首頁"

if st.session_state.mode == "首頁":
    st.header("🏁 開始一場新比賽")
    if st.button("➕ 開始新比賽"):
        st.session_state.mode = "選擇參賽球員"
        st.rerun()
    st.stop()

if "current_game_id" not in st.session_state or not st.session_state.current_game_id:
    st.warning("⚠️ 尚未建立比賽，請先從首頁建立新比賽")
    st.stop()

course_df = load_course_db()
game_id = st.session_state.current_game_id
game_data = load_game_from_drive(game_id)

if not game_data:
    st.error("⚠️ 找不到該比賽資料")
    st.stop()

st.subheader("📋 比賽資訊")
col1, col2 = st.columns([1, 4])
with col1:
    qr_buf = generate_qr(f"{BASE_URL}?game_id={game_id}")
    st.image(qr_buf.getvalue(), width=120)
with col2:
    st.markdown(f"**球場名稱**: {game_data.get('course_name', '未設定')}")
    st.markdown(f"**賭金/人**: 💰 {game_data['bet_per_person']}")
    for p in game_data['players']:
        st.markdown(f"👤 {p}（差點 {game_data['handicaps'][p]}）")

areas_df = course_df[course_df["course_name"] == game_data.get("course_name")]
valid_areas = (
    areas_df.groupby("area").filter(lambda df: len(df) == 9)["area"].unique()
)

front9 = st.selectbox("🏞️ 前九洞區域", valid_areas, index=valid_areas.tolist().index(game_data.get("area_front9", valid_areas[0])))
back9 = st.selectbox("🌇 後九洞區域", valid_areas, index=valid_areas.tolist().index(game_data.get("area_back9", valid_areas[-1])))

front9_df = areas_df[areas_df["area"] == front9].sort_values("hole")
back9_df = areas_df[areas_df["area"] == back9].sort_values("hole")

if len(front9_df) == 9 and len(back9_df) == 9:
    new_par = front9_df["par"].tolist() + back9_df["par"].tolist()
    new_hcp = front9_df["hcp"].tolist() + back9_df["hcp"].tolist()
    game_data["par"] = new_par
    game_data["hcp"] = new_hcp
    game_data["area_front9"] = front9
    game_data["area_back9"] = back9
    game_data["course_name"] = game_data.get("course_name", "")
    save_game_to_drive(game_data, game_id)
else:
    st.error("⚠️ 選擇的區域不是完整9洞")
    st.stop()

new_bet = st.number_input("💵 賭金調整 (即時儲存)", 10, 1000, game_data["bet_per_person"])
if new_bet != game_data["bet_per_person"]:
    game_data["bet_per_person"] = new_bet
    save_game_to_drive(game_data, game_id)

current_hole = game_data['completed']
if current_hole >= 18:
    st.success("🏁 比賽已完成！")
    st.stop()

st.subheader(f"🎯 第 {current_hole + 1} 洞 (Par {game_data['par'][current_hole]} / HCP {game_data['hcp'][current_hole]})")

EVENT_OPTIONS = {
    "無": "",
    "OB": "OB",
    "水池": "water",
    "沙坑": "sand",
    "加三或三推": "trible or 3 putt",
    "丟球": "lost",
    "par on": "par on",
    "未過女tee": "f-tee"
}

scores = {}
events = {}
cols = st.columns(len(game_data["players"]))
for idx, p in enumerate(game_data["players"]):
    with cols[idx]:
        scores[p] = st.number_input(f"{p} 擊數", 1, 15, key=f"score_{p}_{current_hole}")
        event_display = st.selectbox(f"{p} 事件", list(EVENT_OPTIONS.keys()), index=0, key=f"event_{p}_{current_hole}")
        events[p] = EVENT_OPTIONS[event_display]

if st.button(f"✅ 確認第 {current_hole + 1} 洞成績"):
    for p in game_data["players"]:
        game_data["scores"][p][str(current_hole)] = scores[p]
        if p not in game_data["events"]:
            game_data["events"][p] = {}
        game_data["events"][p][str(current_hole)] = events[p]
    game_data["hole_logs"].append(f"第 {current_hole + 1} 洞完成")
    game_data["completed"] += 1
    save_game_to_drive(game_data, game_id)
    st.rerun()
