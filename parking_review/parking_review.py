import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# 设置页面配置
st.set_page_config(layout="wide",page_title="停車申請管理系統")


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

def load_data4(current):
    conn = connect_db()
    query = """
    SELECT 
        A.期別,
        A.單位,
        A.姓名代號,
        A.姓名,
        A.聯絡電話,
        A.身分註記,
        A.車牌號碼,
        B.車位編號,
        C.車位備註,
        B.繳費狀態 
    FROM 申請紀錄 A
    INNER JOIN 抽籤繳費 B ON A.期別 = B.期別 AND A.姓名代號 = B.姓名代號
    LEFT JOIN 停車位 C ON B.車位編號 = C.車位編號
    WHERE A.期別 = ? AND  A.身分註記 != '一般'
    """
    df = pd.read_sql_query(query, conn, params=(current,))
    conn.close()
    return df

def load_data5(current):
    conn = connect_db()
    query = """
    SELECT 
        A.期別,
        A.單位,
        A.姓名代號,
        A.姓名,
        A.聯絡電話,
        A.身分註記,
        A.車牌號碼,
        B.車位編號,
        C.車位備註,
        B.繳費狀態,
        B.發票號碼 
    FROM 申請紀錄 A
    INNER JOIN 抽籤繳費 B ON A.期別 = B.期別 AND A.姓名代號 = B.姓名代號
    LEFT JOIN 停車位 C ON B.車位編號 = C.車位編號
    WHERE A.期別 = ?
    """
    df = pd.read_sql_query(query, conn, params=(current,))
    conn.close()
    return df

def load_data6():
    conn = connect_db()
    query = """
    SELECT 
        A.姓名代號
        A.姓名
        A.單位
        A.車牌號碼
        A.聯絡電話
        A.身分註記
        A.車位編號
        B.使用狀態
        B.車位備註
    FROM 免申請 A
    INNER JOIN 停車位 B ON A.車位編號 = B.車位編號
    """

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

def update_record_car_id(period, name_code, car_id):
    conn = connect_db()
    cursor = conn.cursor()
    update_query = """
    UPDATE 申請紀錄
    SET 車牌號碼 = ?
    WHERE 期別 = ? AND 姓名代號 = ?
    """
    cursor.execute(update_query, (car_id, period, name_code))
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

def insert_parking_fee(current,employee_id):
    conn = connect_db()
    cursor = conn.cursor()
    insert_query = """
    INSERT INTO 抽籤繳費 (期別,姓名代號,繳費狀態)
    VALUES (?,?,'未繳費')
    """
    cursor.execute(insert_query, (current,employee_id))
    conn.commit()
    conn.close()

def update_parking_space(space_id, status, note):
    conn = connect_db()
    cursor = conn.cursor()
    update_query = """
    UPDATE 停車位
    SET 使用狀態 = ? , 車位備註 = ?
    WHERE 車位編號 = ? 
    """
    cursor.execute(update_query, (status, note, space_id))
    conn.commit()
    conn.close()

def update_parking_note(space_id, note):
    conn = connect_db()
    cursor = conn.cursor()
    update_query = """
    UPDATE 停車位
    SET  車位備註 = ?
    WHERE 車位編號 = ? 
    """
    cursor.execute(update_query, (note, space_id))
    conn.commit()
    conn.close()

def parking_distribution(space_id, current, employee_id):
    conn = connect_db()
    cursor = conn.cursor()
    update_query = """
    UPDATE 抽籤繳費
    SET 車位編號 = ? 
    WHERE 期別 = ?  AND 姓名代號 = ?
    """
    cursor.execute(update_query, (space_id, current, employee_id))
    conn.commit()
    conn.close()

def update_payment(car_id, payment_status, bill_number, current, employee_id):
    conn = connect_db()
    cursor = conn.cursor()
    update_query = """
    UPDATE 抽籤繳費
    SET 車位編號 = ? , 繳費狀態 = ? , 發票號碼 = ?
    WHERE 期別 = ?  AND 姓名代號 = ?
    """
    cursor.execute(update_query, (car_id, payment_status, bill_number, current, employee_id))
    conn.commit()
    conn.close()

# 函數來發送電子郵件
def send_email(employee_id, name, text, subject_text):
    sender_email = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    smtp_server = "smtp.gmail.com"
    smtp_port = 465

    subject = subject_text
    body = f"{name}您好,\n{text}\n秘書處 大樓管理組 敬上\n聯絡電話:(02)2366-6395"

    # 建立 MIMEText 物件
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = f"u{employee_id}@taipower.com.tw"
    message["Subject"] = subject

    # 附加郵件內容
    message.attach(MIMEText(body, "plain"))

    # 使用 smtplib 發送郵件
    try:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email,f"u{employee_id}@taipower.com.tw",message.as_string())
        server.close()
        return "郵件已發送成功！"
    except Exception as e:
        return f"發送郵件時發生錯誤: {e}"
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
tab1, tab2, tab4, tab5, tab6= st.tabs(["停車申請待審核", "本期停車申請一覽表", "免抽籤名單分配車位", "本期員工停車繳費維護", "地下停車一覽表"])

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
                        subject_text = '本期停車抽籤申請文件審核通過通知'
                        text = '本期停車抽籤申請資料審核通過，謝謝您。'
                        send_email(row['姓名代號'], row['姓名'], text, subject_text)
                        st.success("審核完成")
                    else:
                        subject_text = '本期停車申請文件審核通過通知'
                        text = '本期停車申請資料審核通過，謝謝您。'
                        send_email(row['姓名代號'], row['姓名'], text, subject_text)
                        st.success("審核完成")
                    if row['身分註記'] != '一般':
                        insert_parking_fee(current, row['姓名代號'])
                elif row['不通過']:
                    subject_text = '本期停車申請文件未審核通過通知'
                    text = '您申請的資料不符合停車要點規定，造成困擾敬請見諒。'
                    send_email(row['姓名代號'], row['姓名'], text, subject_text)
                    delete_record(row['期別'], row['姓名代號'])
                    st.success("審核完成")
        finally:
            upload_db(local_db_path, db_file_id)

with tab2:
    st.header("本期停車申請一覽表")
    name = st.text_input("請輸入要篩選的姓名", key="name_input_tab2") 
    df2 = load_data2(current)
    if name:
        df2 = df2[df2['姓名'].str.contains(name)]
    df2['更新資料'] = False
    df2['刪除資料'] = False
    editable_columns = ['車牌號碼','更新資料','刪除資料']
    disabled_columns = [col for col in df2.columns if col not in editable_columns]
    edited_df2 = st.data_editor(df2, disabled=disabled_columns, key="data_editor_tab2")
    
    button1, button2, button3 = st.columns(3)
    
    with button1:
        if st.button('刪除確認', key="delete_confirm_button"):
            try:
                for index, row in edited_df2.iterrows():
                    if row['刪除資料']:
                        delete_record(row['期別'], row['姓名代號'])
                        st.success("資料刪除成功")
            finally:
                upload_db(local_db_path, db_file_id)
                
    with button2:
        if st.button('免抽籤準備分配車位', key="prepare_parking_button"):
            try:
                for index, row in edited_df2.iterrows():
                    if row['身分註記'] != '一般' and row['車牌綁定'] == True:
                        insert_parking_fee(row['期別'], row['姓名代號'])
                st.success('免抽籤資料匯入成功')
            except:
                st.error('本期免抽籤資料已經匯入進繳費表')
            finally:
                upload_db(local_db_path, db_file_id)

    with button3:
        if st.button('更新確認', key="update_confirm_button"):
            try:
                for index, row in edited_df2.iterrows():
                    if row['更新資料']:
                        update_record_car_id(row['期別'], row['姓名代號'], row['車牌號碼'])
                st.success('車牌更新成功')
            finally:
                upload_db(local_db_path, db_file_id)
with tab4:
    st.header("地下停車位使用狀態維護")  
    # 加載數據
    df4 = load_data3()
    df4['更新資料'] = False

    # 定義下拉選單選項
    options = ["公務車", "公務車(電動)", "值班", "高階主管", "獨董", "公務保留", "身心障礙", "孕婦", "保障", "抽籤"]

    # 添加篩選條件選擇框
    filter_option = st.selectbox("篩選使用狀態", ["所有"] + options)

    # 根據篩選條件過濾數據框
    if filter_option != "所有":
        df4 = df4[df4['使用狀態'] == filter_option]

    # 禁用的列
    column1 = ['車位編號']
    disabled_columns1 = [col for col in df4.columns if col in column1]

    # 顯示可編輯的數據框
    edited_df4 = st.data_editor(
        df4,
        disabled=disabled_columns1,
        column_config={
            "使用狀態": st.column_config.SelectboxColumn(
                "使用狀態",
                options=options,
                help="請選擇該車位用途",
                required=True
            )
        }
    )

    # 更新確認按鈕
    if st.button('更新確認'):
        try:
            for index, row in edited_df4.iterrows():
                if row['更新資料']:
                    update_parking_space(row['車位編號'], row['使用狀態'], row['車位備註'])
                    st.success('資料更新成功')
        finally:
            upload_db(local_db_path, db_file_id)

    st.header("免抽籤名單分配車位")
    df5 = load_data4(current)
    df5['分配車位'] = False
    editable_column = ['車位編號','分配車位']
    disabled_columns2 = [col for col in df5.columns if col not in editable_column]

    edited_df5 = st.data_editor(
        df5,
        disabled=disabled_columns2)
    
    if st.button('分配車位確認'):
        try:
            for index, row in edited_df5.iterrows():
                if row['分配車位']:
                    parking_distribution(row['車位編號'],row['期別'],row['姓名代號'])
                    st.success('車位分配成功')
        finally:
            upload_db(local_db_path, db_file_id)
with tab5:
    st.header("本期員工停車繳費維護")

    # 姓名输入框
    name = st.text_input("請輸入要篩選的姓名") 

    # 篩選條件下拉選單
    filter_option = st.selectbox(
        "選擇車位篩選條件",
        ["所有", "正取", "備取"]
    )

    df6 = load_data5(current)

    # 根據姓名篩選數據
    if name:
        df6 = df6[df6['姓名'].str.contains(name)]
        
    # 确保 '車位編號' 列为字符串，并填充 NaN 值
    df6['車位編號'] = df6['車位編號'].astype(str).fillna('')

    # 根據選擇的篩選條件進行進一步篩選
    if filter_option == "正取":
        df6 = df6[df6['車位編號'].str.startswith('B')]
    elif filter_option == "備取":
        df6 = df6[df6['車位編號'].str.startswith('備取')]
    df6['更新資訊'] = False
    editable_columns = ['車位編號','車位備註','繳費狀態', '發票號碼', '更新資訊']
    options = ['已繳費', '未繳費', '放棄']
    disabled_columns = [col for col in df6.columns if col not in editable_columns]
        
    edited_df6 = st.data_editor(
        df6,
        disabled=disabled_columns,
        column_config={
            "繳費狀態": st.column_config.SelectboxColumn(
                "繳費狀態",
                options=options,
                help="請選擇繳費狀態",
                required=True
            )
        }
    )
    button1, button2 = st.columns(2)
    with button1:
        if st.button('更新資訊確認'):
            try:
                for index, row in edited_df6.iterrows():
                    if row['更新資訊']:
                        update_payment(row['車位編號'], row['繳費狀態'], row['發票號碼'], row['期別'], row['姓名代號'])
                        update_parking_note(row['車位編號'],  row['車位備註'])
                        st.success('資料更新成功')
            finally:
                upload_db(local_db_path, db_file_id)

with tab6:
    st.header("地下停車一覽表") 
    # 姓名输入框
    name = st.text_input("請輸入要篩選的姓名", key="text_input_name_tab6") 
    df7 = load_data6()
    # 根據姓名篩選數據
    if name:
        df7 = df7[df7['姓名'].str.contains(name)]
    uneditable_columns = ['車牌號碼']
    disabled_columns = [col for col in df7.columns if col in uneditable_columns]
        
    edited_df6 = st.data_editor(
        df7,
        disabled=disabled_columns
      )
