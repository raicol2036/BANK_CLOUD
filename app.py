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

st.set_page_config(page_title="🏌️ Golf BANK v3.2", layout="wide")
st.title("🏌️ Golf BANK 系統")

if "mode" not in st.session_state:
    st.session_state.mode = "選擇參賽球員"
if "current_game_id" not in st.session_state:
    st.session_state.current_game_id = ""

@st.cache_data
def load_course_db():
    return pd.read_csv("course_db.csv")

@st.cache_data
def load_players():
    df = pd.read_csv("players.csv")
    return df["name"].dropna().tolist()

course_df = load_course_db()
all_players = load_players()

mode = st.session_state.mode

if mode == "選擇參賽球員":
    st.header("👥 選擇參賽球員（最多4位）")
    player_names = st.multiselect("選擇球員", all_players, key="player_select")
    if len(player_names) > 4:
        st.error("⚠️ 最多只能選擇4位球員參賽")
    elif len(player_names) == 4:
        st.success("✅ 已選擇4位球員")
        st.session_state.selected_players = player_names
        st.session_state.mode = "設定比賽資料"
        st.rerun()

elif mode == "設定比賽資料":
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

    if st.button("✅ 開始球局"):
        game_id = str(uuid.uuid4())[:8]
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
        st.session_state.current_game_id = game_id
        st.session_state.mode = "主控端成績輸入"
        st.rerun()

elif mode == "主控端成績輸入":
    game_id = st.session_state.current_game_id
    game_data = load_game_from_drive(game_id)

    if not game_data:
        st.error("⚠️ 找不到該比賽資料")
        st.stop()

    current_hole = game_data['completed']
    if current_hole >= 18:
        st.success("🏁 比賽已完成！")
        st.write(game_data["hole_logs"])
        st.stop()

    st.subheader(f"🎯 第 {current_hole + 1} 洞輸入")
    par = game_data["par"][current_hole]
    hcp = game_data["hcp"][current_hole]
    st.markdown(f"Par: {par} / HCP: {hcp}")

    scores = {}
    cols = st.columns(len(game_data["players"]))
    for idx, p in enumerate(game_data["players"]):
        with cols[idx]:
            scores[p] = st.number_input(f"{p}", 1, 15, key=f"score_{p}_{current_hole}_input")

    
    if st.button("✅ 確認第{}洞成績".format(current_hole + 1)):
        if not all(p in scores for p in game_data["players"]):
            st.error("❌ 成績輸入不完整")
            st.stop()

        for p in game_data["players"]:
            game_data["scores"][p][str(current_hole)] = scores[p]

        game_data["hole_logs"].append(f"Hole {current_hole + 1} 完成")
        game_data["completed"] += 1
        save_game_to_drive(game_data, game_id)
        st.rerun()

st.caption("Golf BANK v3.2 三段式流程版")
