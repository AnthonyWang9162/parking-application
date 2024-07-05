import time
import fcntl
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import io

# 设置 Google Drive API 凭据
creds = Credentials.from_service_account_info(st.secrets["google_drive"])

# 连接到 Google Drive API
service = build('drive', 'v3', credentials=creds)

# 下载和上传 SQLite 数据库文件的函数
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

# 连接到 SQLite 数据库，并添加文件锁逻辑
def connect_db():
    local_db_path = '/tmp/test.db'
    conn = sqlite3.connect(local_db_path)
    return conn, local_db_path

# 加锁函数
def acquire_lock(file_path):
    lock_file = open(file_path, 'a')
    fcntl.flock(lock_file, fcntl.LOCK_EX)
    return lock_file

# 解锁函数
def release_lock(lock_file):
    fcntl.flock(lock_file, fcntl.LOCK_UN)
    lock_file.close()

# 读取申请记录表
def load_data1():
    conn, db_path = connect_db()
    lock_file = acquire_lock(db_path)
    try:
        query = "SELECT * FROM 申請紀錄 WHERE 車牌綁定 = 0"
        df = pd.read_sql_query(query, conn)
    finally:
        release_lock(lock_file)
        conn.close()
    return df

# 读取当前季度的申请记录表
def load_data2(current):
    conn, db_path = connect_db()
    lock_file = acquire_lock(db_path)
    try:
        query = "SELECT * FROM 申請紀錄 WHERE 期別 = ?"
        df = pd.read_sql_query(query, conn, params=(current,))
    finally:
        release_lock(lock_file)
        conn.close()
    return df

# 更新数据库中的记录
def update_record(period, name_code, plate_binding):
    conn, db_path = connect_db()
    lock_file = acquire_lock(db_path)
    try:
        cursor = conn.cursor()
        update_query = """
        UPDATE 申請紀錄
        SET 車牌綁定 = ?
        WHERE 期別 = ? AND 姓名代號 = ?
        """
        cursor.execute(update_query, (plate_binding, period, name_code))
        conn.commit()
    finally:
        release_lock(lock_file)
        conn.close()

# 删除数据库中的记录
def delete_record(period, name_code):
    conn, db_path = connect_db()
    lock_file = acquire_lock(db_path)
    try:
        cursor = conn.cursor()
        delete_query = """
        DELETE FROM 申請紀錄
        WHERE 期別 = ? AND 姓名代號 = ?
        """
        cursor.execute(delete_query, (period, name_code))
        conn.commit()
    finally:
        release_lock(lock_file)
        conn.close()

def new_approved_car_record(employee_id, car_number):
    conn, db_path = connect_db()
    lock_file = acquire_lock(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM 使用者車牌 WHERE 姓名代號 = ? AND 車牌號碼 = ?", (employee_id, car_number))
        output = cursor.fetchone()
        conn.commit()
    finally:
        release_lock(lock_file)
        conn.close()
    return output is None

# 新增数据库中的记录
def insert_record(unit, name, car_number, employee_id, special_needs, contact_info, car_bind, current):
    conn, db_path = connect_db()
    lock_file = acquire_lock(db_path)
    try:
        cursor = conn.cursor()
        current_date = datetime.now().strftime('%Y-%m-%d')
        insert_query = """
        INSERT INTO 申請紀錄 (日期,期別,姓名代號,姓名,單位,車牌號碼,聯絡電話,身分註記,車牌綁定)
        VALUES (?,?,?,?,?,?,?,?,?)
        """
        cursor.execute(insert_query, (current_date, current, employee_id, name, unit, car_number, contact_info, special_needs, car_bind))
        conn.commit()
    finally:
        release_lock(lock_file)
        conn.close()

def insert_car_approved_record(employee_id, car_number):
    conn, db_path = connect_db()
    lock_file = acquire_lock(db_path)
    try:
        cursor = conn.cursor()
        insert_query = """
        INSERT INTO 使用者車牌 (姓名代號,車牌號碼)
        VALUES (?,?)
        """
        cursor.execute(insert_query, (employee_id, car_number))
        conn.commit()
    finally:
        release_lock(lock_file)
        conn.close()

# 获取当前日期并计算当前期别
today = datetime.today()
year, quarter = get_quarter(today.year, today.month)
Taiwan_year = year - 1911
current = f"{Taiwan_year}{quarter:02}"

# Google Drive 文件 ID（你需要手动获取）
db_file_id = '1_TArAUZyzzZuLX3y320VpytfBlaoUGBB'

# 下载数据库文件到本地
local_db_path = '/tmp/test.db'
download_db(db_file_id, local_db_path)

# 设置 Streamlit 页面配置
st.set_page_config(layout="wide")
st.title("停車申請管理系統")

# 创建选项卡
tab1, tab2, tab3 = st.tabs(["停車申請待審核", "本期停車申請一覽表", "新增資料"])

with tab1:
    st.header("停車申請待審核")
    df1 = load_data1()
    df1['通過'] = False
    df1['不通過'] = False
    edited_df1 = st.data_editor(df1)
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
    edited_df2 = st.data_editor(df2)
    if st.button('刪除確認'):
        try:
            for index, row in edited_df2.iterrows():
                if row['刪除資料']:
                    delete_record(row['期別'], row['姓名代號'])
                    st.success("資料刪除成功")
        finally:
            upload_db(local_db_path, db_file_id)
