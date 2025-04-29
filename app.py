import streamlit as st
import pandas as pd
import json
import uuid
import qrcode
from io import BytesIO
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.service_account import ServiceAccountCredentials
import os

# --- Google Drive 設定 ---
GAMES_FOLDER_ID = "1G2VWwDHOHhnOKBNdnlut1oG5BOoUYAuf"

# --- 初始化 Google Drive ---
from google.oauth2 import service_account
from googleapiclient.discovery import build

def connect_drive():
    credentials = service_account.Credentials.from_service_account_info(
        st.secrets["gdrive"],
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build('drive', 'v3', credentials=credentials)

drive_service = connect_drive()

# --- 常數設定 ---
CSV_PATH = "course_db.csv"
PLAYER_PATH = "players.csv"

st.set_page_config(page_title="🏌️ Golf BANK System", layout="wide")
st.title("🏌️ Golf BANK 系統")

# --- 輔助 Functions ---
def save_game_to_drive(game_data, game_id):
    from googleapiclient.http import MediaInMemoryUpload
    query = f"name='game_{game_id}.json' and '{GAMES_FOLDER_ID}' in parents and trashed=false"
    results = drive_service.files().list(q=query, spaces='drive').execute()
    items = results.get('files', [])
    media = MediaInMemoryUpload(json.dumps(game_data, ensure_ascii=False, indent=2).encode(), mimetype='application/json')
    if items:
        file_id = items[0]['id']
        drive_service.files().update(fileId=file_id, media_body=media).execute()
    else:
        file_metadata = {'name': f'game_{game_id}.json', 'parents': [GAMES_FOLDER_ID]}
        drive_service.files().create(body=file_metadata, media_body=media).execute()

def load_game_from_drive(game_id):
    query = f"name='game_{game_id}.json' and '{GAMES_FOLDER_ID}' in parents and trashed=false"
    results = drive_service.files().list(q=query, spaces='drive').execute()
    items = results.get('files', [])
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

# --- 模式選擇 ---
mode = st.radio("選擇模式", ["建立新比賽", "主控端成績輸入", "隊員查看比賽", "歷史紀錄管理"])

# --- 建立新比賽 ---
if mode == "建立新比賽":
    game_id = str(uuid.uuid4())[:8]
    st.success(f"✅ 新比賽ID：{game_id}")

    course_df = pd.read_csv(CSV_PATH)
    course_options = course_df["course_name"].unique().tolist()
    area_options = course_df["area"].unique().tolist()

    front_course = st.selectbox("前九洞球場", [f"{c}-{a}" for c in course_options for a in area_options], key="front")
    back_course = st.selectbox("後九洞球場", [f"{c}-{a}" for c in course_options for a in area_options], key="back")

    def get_course_info(selection):
        cname, area = selection.split("-")
        temp = course_df[(course_df["course_name"] == cname) & (course_df["area"] == area)]
        temp = temp.sort_values("hole")
        return temp["par"].tolist(), temp["hcp"].tolist()

    front_par, front_hcp = get_course_info(front_course)
    back_par, back_hcp = get_course_info(back_course)

    par = front_par + back_par
    hcp = front_hcp + back_hcp

    players_df = pd.read_csv(PLAYER_PATH)
    players = st.multiselect("選擇參賽球員（最多4位）", players_df["name"].tolist(), max_selections=4)

    new = st.text_input("新增球員")
    if new:
        if new not in players_df["name"].tolist():
            players_df = players_df.append({"name": new}, ignore_index=True)
            players_df.to_csv(PLAYER_PATH, index=False)
            st.success(f"✅ 已新增球員 {new}")

    handicaps = {p: st.number_input(f"{p} 差點", 0, 54, 0, key=f"hcp_{p}") for p in players}
    bet_per_person = st.number_input("單局賭金（每人）", 10, 1000, 100)

    if st.button("✅ 建立比賽"):
        game_data = {
            "game_id": game_id,
            "players": players,
            "handicaps": handicaps,
            "par": par,
            "hcp": hcp,
            "front_course": front_course,
            "back_course": back_course,
            "bet_per_person": bet_per_person,
            "scores": {},
            "events": {},
            "running_points": {p: 0 for p in players},
            "current_titles": {p: "" for p in players},
            "hole_logs": [],
            "completed": 0
        }
        save_game_to_drive(game_data, game_id)
        st.success("✅ 比賽已成功建立")

        base_url = st.text_input("輸入查看頁面 Base URL", "https://你的網站/查看")
        view_url = f"{base_url}?game_id={game_id}"
        buf = generate_qr(view_url)
        st.image(buf)

# (其餘主控端成績輸入、隊員查看、歷史紀錄管理，因字數限制繼續補充）
