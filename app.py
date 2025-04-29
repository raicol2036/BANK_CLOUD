import streamlit as st
import pandas as pd
import json
import uuid
import qrcode
from io import BytesIO
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === Google Drive 連接 ===
GAMES_FOLDER_ID = "1G2VWwDHOHhnOKBNdnlut1oG5BOoUYAuf"  # 你的Google Drive資料夾ID

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

# === 小工具 Functions ===
def save_game_to_drive(game_data, game_id):
    from googleapiclient.http import MediaInMemoryUpload
    query = f"(name='game_{game_id}.json') and ('{GAMES_FOLDER_ID}' in parents) and (trashed=false)"
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

def list_all_games():
    query = f"'{GAMES_FOLDER_ID}' in parents and trashed=false"
    results = drive_service.files().list(q=query, spaces='drive').execute()
    return results.get('files', [])

def generate_qr(url):
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf)
    return buf

# === 主畫面 ===
st.set_page_config(page_title="🏌️ Golf BANK System", layout="wide")
st.title("🏌️ Golf BANK 系統")

mode = st.sidebar.radio("選擇模式", ["建立新比賽", "主控端成績輸入", "隊員查看比賽", "歷史紀錄管理"])

# === 建立新比賽 ===
if mode == "建立新比賽":
    game_id = str(uuid.uuid4())[:8]
    st.success(f"✅ 新比賽ID：{game_id}")

    players = st.text_input("輸入球員名稱（用逗號分隔）", "Alice,Bob,Charlie,David").split(",")
    handicaps = {p: st.number_input(f"{p.strip()} 差點", 0, 54, 0) for p in players}

    par = [4, 4, 3, 5, 4, 4, 3, 5, 4, 5, 4, 3, 4, 4, 3, 4, 5, 4]
    hcp = list(range(1, 19))

    bet_per_person = st.number_input("單人賭金", 10, 1000, 100)

    if st.button("✅ 建立比賽"):
        game_data = {
            "game_id": game_id,
            "players": players,
            "handicaps": handicaps,
            "par": par,
            "hcp": hcp,
            "bet_per_person": bet_per_person,
            "scores": {},
            "events": {},
            "running_points": {p.strip(): 0 for p in players},
            "current_titles": {p.strip(): "" for p in players},
            "hole_logs": [],
            "completed": 0
        }
        save_game_to_drive(game_data, game_id)
        st.success("✅ 比賽已建立成功！")

        base_url = st.text_input("查看用 Base URL", "https://你的網址")
        view_url = f"{base_url}?game_id={game_id}"
        buf = generate_qr(view_url)
        st.image(buf)

# === 主控端成績輸入 ===
elif mode == "主控端成績輸入":
    game_id = st.text_input("輸入比賽ID")
    if game_id:
        game_data = load_game_from_drive(game_id)
        if not game_data:
            st.error("找不到該比賽！")
            st.stop()
        players = game_data['players']
        for i in range(18):
            st.subheader(f"第{i+1}洞（Par {game_data['par'][i]}，HCP {game_data['hcp'][i]}）")
            cols = st.columns(len(players))
            for idx, p in enumerate(players):
                with cols[idx]:
                    score = st.number_input(f"{p} 桿數", min_value=1, max_value=15, key=f"score_{p}_{i}")
                    event = st.multiselect(f"{p} 事件", ["OB", "水障礙", "下沙", "3推"], key=f"event_{p}_{i}")
                    game_data['scores'].setdefault(p, {})[str(i)] = score
                    game_data['events'].setdefault(p, {})[str(i)] = event
            if st.button(f"✅ 確認第{i+1}洞", key=f"confirm_{i}"):
                game_data['completed'] += 1
                save_game_to_drive(game_data, game_id)
                st.success("✅ 已同步！")

# === 隊員查看比賽 ===
elif mode == "隊員查看比賽":
    game_id = st.text_input("輸入比賽ID")
    if game_id:
        game_data = load_game_from_drive(game_id)
        if game_data:
            st.subheader("📊 總結成績")
            players = game_data['players']
            result = pd.DataFrame({
                "總點數": [game_data['running_points'][p] for p in players],
                "頭銜": [game_data['current_titles'][p] for p in players]
            }, index=players)
            st.dataframe(result, use_container_width=True)
            st.subheader("📖 洞別Log")
            for log in game_data['hole_logs']:
                st.markdown(f"- {log}")

# === 歷史紀錄管理 ===
elif mode == "歷史紀錄管理":
    files = list_all_games()
    game_list = [f["name"].replace("game_", "").replace(".json", "") for f in files]
    selected_game = st.selectbox("選擇要查看的比賽", game_list)
    if selected_game:
        st.info(f"你選擇了比賽 ID: {selected_game}")

st.caption("Golf BANK System © 2024")
