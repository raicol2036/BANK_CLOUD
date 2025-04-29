import streamlit as st
import pandas as pd
import os
import json
import uuid
import qrcode
from io import BytesIO
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.service_account import ServiceAccountCredentials

# --- Google Drive 設定 ---
GAMES_FOLDER_ID = "1G2VWwDHOHhnOKBNdnlut1oG5BOoUYAuf"
SERVICE_ACCOUNT_FILE = "service_account.json"

# --- 初始化 ---
gauth = GoogleAuth()
gauth.LoadServiceConfigSettings()
gauth.ServiceAuth()
drive = GoogleDrive(gauth)

# --- 常數設定 ---
CSV_PATH = "players.csv"
COURSE_DB_PATH = "course_db.csv"

if "players" not in st.session_state:
    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH)
        st.session_state.players = df["name"].dropna().tolist()
    else:
        st.session_state.players = []

if os.path.exists(COURSE_DB_PATH):
    course_df = pd.read_csv(COURSE_DB_PATH)
else:
    st.error("找不到 course_db.csv！請先準備好球場資料。")
    st.stop()

st.set_page_config(page_title="🏌️ 高爾夫BANK系統", layout="wide")
st.title("🏌️ 高爾夫BANK系統")

# --- 模式選擇 ---
mode = st.radio("選擇模式", ["建立新比賽", "主控端成績輸入", "隊員查看比賽"])

# --- Functions ---
def save_game_to_drive(game_data, game_id):
    file_list = drive.ListFile({'q': f"'{GAMES_FOLDER_ID}' in parents and trashed=false and title='game_{game_id}.json'"}).GetList()
    if file_list:
        f = file_list[0]
    else:
        f = drive.CreateFile({'title': f"game_{game_id}.json", 'parents': [{'id': GAMES_FOLDER_ID}]})
    f.SetContentString(json.dumps(game_data, ensure_ascii=False, indent=2))
    f.Upload()

def load_game_from_drive(game_id):
    file_list = drive.ListFile({'q': f"'{GAMES_FOLDER_ID}' in parents and trashed=false and title='game_{game_id}.json'"}).GetList()
    if not file_list:
        return None
    f = file_list[0]
    content = f.GetContentString()
    return json.loads(content)

def generate_qr(url):
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf)
    return buf

# --- 建立新比賽 ---
if mode == "建立新比賽":
    game_id = str(uuid.uuid4())[:8]
    st.success(f"✅ 新比賽ID：{game_id}")
    
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
    hcp = back_hcp + back_hcp

    players = st.multiselect("選擇參賽球員（最多4位）", st.session_state.players, max_selections=4)

    new = st.text_input("新增球員")
    if new:
        if new not in st.session_state.players:
            st.session_state.players.append(new)
            pd.DataFrame({"name": st.session_state.players}).to_csv(CSV_PATH, index=False)
            st.success(f"✅ 已新增球員 {new} 至資料庫")

    if len(players) == 0:
        st.warning("⚠️ 請先選擇至少一位球員")
        st.stop()

    handicaps = {p: st.number_input(f"{p} 差點", 0, 54, 0, key=f"hcp_{p}") for p in players}
    bet_per_person = st.number_input("單局賭金（每人）", 10, 1000, 100)

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

    st.success("✅ 比賽已建立，請複製以下 ID 給隊員！")
    st.code(game_id)

    base_url = st.text_input("輸入查看頁面 Base URL", "https://你的網站/查看")
    view_url = f"{base_url}?game_id={game_id}"
    buf = generate_qr(view_url)
    st.image(buf)

# --- 主控端成績輸入 ---
elif mode == "主控端成績輸入":
    game_id = st.text_input("輸入比賽ID")
    if game_id:
        game_data = load_game_from_drive(game_id)
        if not game_data:
            st.error("找不到該比賽資料！")
            st.stop()

        st.subheader(f"比賽：{game_data['front_course']} ➔ {game_data['back_course']}")
        players = game_data['players']

        for i in range(18):
            st.markdown(f"## 第{i+1}洞")
            if f"confirm_{i}" not in st.session_state:
                st.session_state[f"confirm_{i}"] = False

            if not st.session_state[f"confirm_{i}"]:
                for p in players:
                    score = st.number_input(f"{p} 桿數", min_value=1, max_value=15, key=f"score_{p}_{i}")
                    event = st.multiselect(f"{p} 特殊事件", ["OB", "下水", "下沙", "3推"], key=f"event_{p}_{i}")
                    game_data['scores'].setdefault(p, {})[str(i)] = score
                    game_data['events'].setdefault(p, {})[str(i)] = event
                if st.button(f"✅ 確認第{i+1}洞成績", key=f"btn_{i}"):
                    st.session_state[f"confirm_{i}"] = True
                    save_game_to_drive(game_data, game_id)
            else:
                st.success(f"✅ 第{i+1}洞已確認")

        if all(st.session_state.get(f"confirm_{i}", False) for i in range(18)):
            st.success("🎉 比賽完成！")

# --- 隊員查看比賽 ---
elif mode == "隊員查看比賽":
    game_id = st.text_input("輸入比賽ID")
    if game_id:
        game_data = load_game_from_drive(game_id)
        if game_data:
            st.subheader("📊 總結結果")
            players = game_data["players"]
            result = pd.DataFrame({
                "總點數": [game_data["running_points"][p] for p in players],
                "頭銜": [game_data["current_titles"][p] for p in players]
            }, index=players)
            st.dataframe(result)

            st.subheader("📖 洞別說明 Log")
            for line in game_data["hole_logs"]:
                st.text(line)
        else:
            st.error("找不到該比賽資料！")
