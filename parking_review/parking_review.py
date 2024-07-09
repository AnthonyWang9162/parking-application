import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import io

# 设置页面配置
st.set_page_config(layout="wide", page_title="停車申請管理系統")

# 设置 Google Drive API 凭据
creds = Credentials.from_service_account_info(st.secrets["google_drive"])

# 连接到 Google Drive API
service = build('drive', 'v3', credentials=creds)

# 下载和上传 SQLite 数据库文件的函数

def connect_db():
    local_db_path = '/tmp/test.db'
    conn = sqlite3.connect(local_db_path)
    return conn
    
@st.cache_data(ttl=600, show_spinner="正在加載資料...")   
def download_db(file_id, destination):
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(destination, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        
def upload_db(source, file_id):
    file_metadata = {'name': 'test.db'}
    media = MediaFileUpload(source, mimetype='application/x-sqlite3')
    updated_file = service.files().update(
        fileId=file_id,
        media_body=media
    ).execute()

def get_quarter(year, month):
    if 1 <= month <= 3:
        quarter = 2
    elif 4 <= month <= 6:
        quarter = 3
    elif 7 <= month <= 9:
        quarter = 4
    elif 10 <= month <= 12:
        year = year + 1
        quarter = 1
    else:
        raise ValueError("Month must be between 1 and 12")
    return year, quarter

# 读取申请记录表

def load_data1():
    conn = connect_db()
    query = "SELECT * FROM 申請紀錄 WHERE 車牌綁定 = 0"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def load_data2(current):
    conn = connect_db()
    query = "SELECT * FROM 申請紀錄 WHERE 期別 = ?"
    df = pd.read_sql_query(query, conn, params=(current,))
    conn.close()
    return df

def load_data3():
    conn = connect_db()
    query = "SELECT * FROM 停車位 "
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df
# 更新数据库中的记录
def update_record(period, name_code, plate_binding):
    conn = connect_db()
    cursor = conn.cursor()
    update_query = """
    UPDATE 申請紀錄
    SET 車牌綁定 = ?
    WHERE 期別 = ? AND 姓名代號 = ?
    """
    cursor.execute(update_query, (plate_binding, period, name_code))
    conn.commit()
    conn.close()

# 删除数据库中的记录
def delete_record(period, name_code):
    conn = connect_db()
    cursor = conn.cursor()
    delete_query = """
    DELETE FROM 申請紀錄
    WHERE 期別 = ? AND 姓名代號 = ?
    """
    cursor.execute(delete_query, (period, name_code))
    conn.commit()
    conn.close()

def new_approved_car_record(employee_id, car_number):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM 使用者車牌 WHERE 姓名代號 = ? AND 車牌號碼 = ?", (employee_id, car_number))
    output = cursor.fetchone()
    conn.commit()
    conn.close()
    return output is None

# 新增数据库中的记录
def insert_record(unit, name, car_number, employee_id, special_needs, contact_info, car_bind, current):
    conn = connect_db()
    cursor = conn.cursor()
    current_date = datetime.now().strftime('%Y-%m-%d')
    insert_query = """
    INSERT INTO 申請紀錄 (日期,期別,姓名代號,姓名,單位,車牌號碼,聯絡電話,身分註記,車牌綁定)
    VALUES (?,?,?,?,?,?,?,?,?)
    """
    cursor.execute(insert_query, (current_date, current, employee_id, name, unit, car_number, contact_info, special_needs, car_bind))
    conn.commit()
    conn.close()

def insert_car_approved_record(employee_id, car_number):
    conn = connect_db()
    cursor = conn.cursor()
    insert_query = """
    INSERT INTO 使用者車牌 (姓名代號,車牌號碼)
    VALUES (?,?)
    """
    cursor.execute(insert_query, (employee_id, car_number))
    conn.commit()
    conn.close()

def update_parking_space(space_id, status, note):
    conn = connect_db()
    cursor = conn.cursor()
    update_query = """
    UPDATE 停車位
    SET 使用狀態 = ? , 備註 = ?
    WHERE 車位編號 = ? 
    """
    cursor.execute(update_query, (status, note, space_id))
    conn.commit()
    conn.close()


today = datetime.today()
year, quarter = get_quarter(today.year, today.month)
Taiwan_year = year - 1911
current = f"{Taiwan_year}{quarter:02}"

# Google Drive 文件 ID（你需要手动获取）
db_file_id = '1_TArAUZyzzZuLX3y320VpytfBlaoUGBB'

# 下载数据库文件到本地
local_db_path = '/tmp/test.db'
download_db(db_file_id, local_db_path)

st.title("停車申請管理系統")
# 创建选项卡
tab1, tab2, tab3, tab4 = st.tabs(["停車申請待審核", "本期停車申請一覽表", "新增資料", "保障名單分配車位"])

with tab1:
    st.header("停車申請待審核")
    df1 = load_data1()
    df1['通過'] = False
    df1['不通過'] = False
    editable_columns = ['通過', '不通過']
    disabled_columns = [col for col in df1.columns if col not in editable_columns]
    edited_df1 = st.data_editor(df1, disabled=disabled_columns)
    if st.button('審核確認'):
        try:
            for index, row in edited_df1.iterrows():
                if row['通過'] and row['不通過']:
                    st.error("欄位有誤，請調整後再試")
                elif row['通過']:
                    update_record(row['期別'], row['姓名代號'], True)
                    if new_approved_car_record(row['姓名代號'], row['車牌號碼']):
                        insert_car_approved_record(row['姓名代號'], row['車牌號碼'])
                        st.success("審核完成")
                    else:
                        st.success("審核完成")
                elif row['不通過']:
                    delete_record(row['期別'], row['姓名代號'])
                    st.success("審核完成")
        finally:
            upload_db(local_db_path, db_file_id)

with tab2:
    st.header("本期停車申請一覽表")
    df2 = load_data2(current)
    df2['刪除資料'] = False
    editable_columns = ['刪除資料']
    disabled_columns = [col for col in df2.columns if col not in editable_columns]
    edited_df2 = st.data_editor(df2, disabled=disabled_columns)
    if st.button('刪除確認'):
        try:
            for index, row in edited_df2.iterrows():
                if row['刪除資料']:
                    delete_record(row['期別'], row['姓名代號'])
                    st.success("資料刪除成功")
        finally:
            upload_db(local_db_path, db_file_id)

with tab3:
    st.header("新增資料")
    columns = ['單位', '姓名代號', '姓名', '車牌號碼', '身分註記', '聯絡電話']
    options = ["一般", "孕婦", "身心障礙"]
    df3 = pd.DataFrame(columns=columns)
    edited_df3 = st.data_editor(df3, num_rows="dynamic", column_config={"身分註記": st.column_config.SelectboxColumn("身分註記", options=options, help="Select a category", required=True)})
    if st.button('新增確認'):
        for index, row in edited_df3.iterrows():
            try:
                insert_record(row['單位'], row['姓名'], row['車牌號碼'], row['姓名代號'], row['身分註記'], row['聯絡電話'], False, current)
                st.success("資料新增成功")
            except Exception as e:
                st.error(f"資料新增失敗: {e}")

with tab4:
    st.header("地下停車位使用狀態維護")
    df4 = load_data3()
    df4['更新資料'] = False
    column = ['車位編號']
    disabled_columns = [col for col in df4.columns if col in column]
    edited_df4 = st.data_editor(df4, disabled=disabled_columns)
    if st.button('更新確認'):
        try:
            for index, row in edited_df4.iterrows():
                if row['更新資料']:
                    update_parking_space(row['車位編號'], row['使用狀態'], row['備註'])
                    st.success("資料更新成功")
                    
        finally:
            upload_db(local_db_path, db_file_id)
