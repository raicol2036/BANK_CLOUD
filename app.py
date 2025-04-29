import streamlit as st
import pandas as pd
import json
import uuid
import qrcode
from io import BytesIO
from google.oauth2 import service_account
from googleapiclient.discovery import build

BASE_URL = "https://bankcloud.streamlit.app/"

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

st.set_page_config(page_title="🏌️ Golf BANK v3.0", layout="wide")
st.title("\ud83c\udfc9 Golf BANK \u7cfb\u7d71")

if "mode" not in st.session_state:
    st.session_state.mode = None
if "current_game_id" not in st.session_state:
    st.session_state.current_game_id = ""
if "point_bank" not in st.session_state:
    st.session_state.point_bank = 1

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

    players = st.text_input("輸入球員名稱（用逗號分隔）", "Alice,Bob,Charlie,David").split(",")
    handicaps = {p.strip(): st.number_input(f"{p.strip()} 差點", 0, 54, 0) for p in players}

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
        st.session_state.mode = "主控端成績輸入"
        st.session_state.current_game_id = game_id
        st.rerun()

elif mode == "主控端成績輸入":
    if st.session_state.current_game_id:
        game_id = st.session_state.current_game_id
    else:
        game_id = st.text_input("輸入比賽ID")

    if game_id:
        game_data = load_game_from_drive(game_id)
        if not game_data:
            st.error("找不到該比賽！")
            st.stop()

        st.subheader(f"📋 目前比賽資訊")
        st.markdown(f"**比賽ID**：{game_data['game_id']}")
        st.markdown(f"**參賽球員**：{', '.join(game_data['players'])}")
        st.markdown("**差點設定**：")
        for p in game_data["players"]:
            st.markdown(f"- {p}: {game_data['handicaps'][p]}")
        st.markdown(f"**單人賭金**：{game_data['bet_per_person']}")
        view_url = f"{BASE_URL}?game_id={game_data['game_id']}"
        buf = generate_qr(view_url)
        st.image(buf, caption="掃描查看比賽進度")

        players = game_data['players']
        handicaps = game_data['handicaps']
        par = game_data['par']
        hcp = game_data['hcp']
        running_points = game_data['running_points']
        hole_logs = game_data['hole_logs']

        for i in range(18):
            st.subheader(f"第{i+1}洞（Par {par[i]}，HCP {hcp[i]}）")
            cols = st.columns(len(players))
            for idx, p in enumerate(players):
                with cols[idx]:
                    score = st.number_input(f"{p} 桿數", min_value=1, max_value=15, key=f"score_{p}_{i}")
                    game_data['scores'].setdefault(p, {})[str(i)] = score

            if st.button(f"✅ 確認第{i+1}洞", key=f"confirm_{i}"):
                raw_scores = {p: game_data['scores'][p][str(i)] for p in players}

                adjusted_scores = {}
                for p1 in players:
                    adj = 0
                    for p2 in players:
                        if p1 == p2:
                            continue
                        diff = handicaps[p2] - handicaps[p1]
                        if diff > 0 and hcp[i] <= diff:
                            adj += 1
                    adjusted_scores[p1] = raw_scores[p1] - adj

                victories = {p: 0 for p in players}
                for p1 in players:
                    for p2 in players:
                        if p1 == p2:
                            continue
                        if adjusted_scores[p1] < adjusted_scores[p2]:
                            victories[p1] += 1

                winners = [p for p in players if victories[p] == len(players)-1]

                if winners:
                    w = winners[0]
                    running_points[w] += st.session_state.point_bank
                    hole_logs.append(f"🏆 第{i+1}洞勝者：{w}（得 {st.session_state.point_bank} 點）")
                    st.session_state.point_bank = 1
                else:
                    st.session_state.point_bank += 1
                    hole_logs.append(f"⚖️ 第{i+1}洞平手（累積 {st.session_state.point_bank} 點）")

                game_data['running_points'] = running_points
                game_data['hole_logs'] = hole_logs
                game_data['completed'] += 1
                save_game_to_drive(game_data, game_id)
                st.success("✅ 已同步到Google Drive！")

elif mode == "隊員查看比賽":
    if st.session_state.current_game_id:
        game_id = st.session_state.current_game_id
    else:
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

elif mode == "歷史紀錄管理":
    query = f"name contains 'game_' and '{GAMES_FOLDER_ID}' in parents and trashed=false"
    result = drive_service.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    items = result.get('files', [])
    if items:
        options = {item['name'].replace('game_', '').replace('.json', ''): item['id'] for item in items}
        selected_game = st.selectbox("選擇要查看的比賽", list(options.keys()))
        if selected_game:
            file_id = options[selected_game]
            file = drive_service.files().get_media(fileId=file_id).execute()
            game_data = json.loads(file)
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

st.caption("Golf BANK v3.0 System \u00a9 2024")
