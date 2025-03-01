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
import time
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

# 获取字体文件路径
FONT_PATH = 'parking_review/NotoSansTC-SemiBold.ttf'  # 确保将字体文件上传到 Streamlit Cloud 的文件夹

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

def get_actual_quarter(month):
    if 1 <= month <= 3:
        quarter = 1
    elif 4 <= month <= 6:
        quarter = 2
    elif 7 <= month <= 9:
        quarter = 3
    elif 10 <= month <= 12:
        quarter = 4
    else:
        raise ValueError("Month must be between 1 and 12")
    return quarter

def mask_name(name):
    return name[0] + '○' + name[2:] if len(name) > 1 else name

def generate_title(year, quarter):
    if quarter == 1:
        text = f"總管理處{year}年第1期(1-3月)地下停車場員工自用車停車名冊"
    elif quarter == 2:
        text = f"總管理處{year}年第2期(4-6月)地下停車場員工自用車停車名冊"
    elif quarter == 3:
        text = f"總管理處{year}年第3期(7-9月)地下停車場員工自用車停車名冊"
    elif quarter == 4:
        text = f"總管理處{year}年第4期(10-12月)地下停車場員工自用車停車名冊"
    return text

def convert_custom_df_to_pdf(df):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    year, quarter = get_quarter(today.year, today.month)
    Taiwan_year = year - 1911
    title_text = generate_title(Taiwan_year, quarter)

    # 注册字体
    pdfmetrics.registerFont(TTFont('NotoSans', FONT_PATH))

    # 自定义样式
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='CustomTitle', fontName='NotoSans', fontSize=16, spaceAfter=20, alignment=1, textColor=colors.black))
    styles.add(ParagraphStyle(name='CustomTableHeader', fontName='NotoSans', fontSize=12, textColor=colors.white, alignment=1))
    styles.add(ParagraphStyle(name='CustomTableData', fontName='NotoSans', fontSize=12, textColor=colors.black, alignment=1))
    styles.add(ParagraphStyle(name='CustomFooter', fontName='NotoSans', fontSize=12, textColor=colors.black, spaceBefore=20))

    # Add title
    title = Paragraph(f'{title_text}', styles['CustomTitle'])
    elements.append(title)
    elements.append(Spacer(1, 12))

    # Convert dataframe to table data
    table_data = [['單位', '姓名', '車位編號']] + df.values.tolist()

    # Style table header and data
    styled_table_data = []
    for i, row in enumerate(table_data):
        styled_row = []
        for cell in row:
            if i == 0:  # Header
                styled_row.append(Paragraph(str(cell), styles['CustomTableHeader']))
            else:
                styled_row.append(Paragraph(str(cell), styles['CustomTableData']))
        styled_table_data.append(styled_row)

    # Create a Table
    table = Table(styled_table_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),  # Center align all cells
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 12))

    # Add notes with part of the text in red
    note_text = (
        f"備註：本處<font color='red'>審核申請</font>時會<font color='red'>扣除前期停過</font>人員<font color='red'>名單</font>，故<font color='red'>本期已停車</font>之同仁<font color='red'>下期無須申請</font>。"
    )
    note = Paragraph(note_text, styles['CustomFooter'])
    elements.append(note)

    doc.build(elements)
    buffer.seek(0)
    return buffer

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
    query = "SELECT 車位編號,使用狀態,車位備註 FROM 停車位 "
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
    SELECT * FROM(
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
            B.發票號碼,
            C.車位排序
        FROM 申請紀錄 A
        INNER JOIN 抽籤繳費 B ON A.期別 = B.期別 AND A.姓名代號 = B.姓名代號
        LEFT JOIN 停車位 C ON B.車位編號 = C.車位編號
        WHERE A.期別 = ?
        UNION
        SELECT
            E.期別,
            D.單位,
            D.姓名代號,
            D.姓名,
            D.聯絡電話,
            D.身分註記,
            D.車牌號碼,
            D.車位編號,
            C.車位備註,
            E.繳費狀態,
            E.發票號碼,
            C.車位排序
        FROM 免申請 D
        INNER JOIN 免申請繳費 E ON D.姓名代號 = E.姓名代號
        LEFT JOIN 停車位 C ON D.車位編號 = C.車位編號
        WHERE E.期別 = ?)subquery
        ORDER BY COALESCE(車位排序,車位編號)
    """
    df = pd.read_sql_query(query, conn, params=(current,current))
    conn.close()
    # 如果 '車位排序編號' 列存在则删除
    if '車位排序' in df.columns:
        df.drop(columns=['車位排序'], inplace=True)
    return df

def load_data6(current):
    conn = connect_db()
    query = """
    SELECT * FROM (
        SELECT 
            A.姓名代號,
            A.姓名,
            A.單位,
            A.車牌號碼,
            A.聯絡電話,
            A.身分註記,
            A.車位編號,
            B.車位備註,
            B.使用狀態,
            B.車位排序
        FROM 免申請 A
        LEFT JOIN 停車位 B ON A.車位編號 = B.車位編號
        WHERE  A.期別 = ?
        UNION
        SELECT 
            C.姓名代號,
            C.姓名,
            C.單位,
            C.車牌號碼,
            C.聯絡電話,
            C.身分註記,
            D.車位編號,
            B.車位備註,
            B.使用狀態,
            B.車位排序
        FROM 申請紀錄 C
        INNER JOIN 繳費紀錄 D ON C.期別 = D.期別 AND C.姓名代號 = D.姓名代號
        LEFT JOIN 停車位 B ON D.車位編號 = B.車位編號
        WHERE C.期別 = ?
    ) subquery
    ORDER BY 車位排序 
    """

    try:
        df = pd.read_sql_query(query, conn, params=(current,current))
    except Exception as e:
        st.error(f"SQL query failed: {e}")
    finally:
        conn.close()
    
    # 如果 '車位排序編號' 列存在则删除
    if '車位排序' in df.columns:
        df.drop(columns=['車位排序'], inplace=True)
    
    return df

def load_data7(current):
    conn = connect_db()
    query = """
    SELECT * FROM (
        SELECT 
            A.姓名代號,
            A.姓名,
            A.單位,
            A.車牌號碼,
            A.聯絡電話,
            A.身分註記,
            A.車位編號,
            B.車位備註,
            B.使用狀態,
            B.車位排序
        FROM 免申請 A
        LEFT JOIN 停車位 B ON A.車位編號 = B.車位編號
        WHERE A.期別 IS NULL OR A.期別 = ?
        UNION
        SELECT 
            C.姓名代號,
            C.姓名,
            C.單位,
            C.車牌號碼,
            C.聯絡電話,
            C.身分註記,
            D.車位編號,
            B.車位備註,
            B.使用狀態,
            B.車位排序
        FROM 申請紀錄 C
        INNER JOIN 繳費紀錄 D ON C.期別 = D.期別 AND C.姓名代號 = D.姓名代號
        LEFT JOIN 停車位 B ON D.車位編號 = B.車位編號
        WHERE C.期別 = ?
        UNION
        SELECT 
            A.姓名代號,
            A.姓名,
            A.單位,
            A.車牌號碼,
            A.聯絡電話,
            A.身分註記,
            B.車位編號,
            B.車位備註,
            B.使用狀態,
            B.車位排序
        FROM 停車位 B
        LEFT JOIN 免申請 A ON A.車位編號 = B.車位編號
        WHERE B.車位編號 NOT IN (SELECT 車位編號 FROM 免申請 UNION SELECT 車位編號 FROM 繳費紀錄 WHERE 期別 = ? )
    ) subquery
    ORDER BY 車位排序
    """

    try:
        df = pd.read_sql_query(query, conn, params=(current,current,current))
    except Exception as e:
        st.error(f"SQL query failed: {e}")
    finally:
        conn.close()
    
    # 如果 '車位排序編號' 列存在则删除
    if '車位排序' in df.columns:
        df.drop(columns=['車位排序'], inplace=True)
    
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

def update_application_record(period, name, unit, name_code, car_id, contact_number):
    conn = connect_db()
    cursor = conn.cursor()
    update_query = """
    UPDATE 申請紀錄
    SET 姓名 = ? , 單位 = ? , 車牌號碼 = ? , 聯絡電話 = ? 
    WHERE 期別 = ? AND 姓名代號 = ?
    """
    cursor.execute(update_query, (name, unit, car_id, contact_number, period, name_code))
    conn.commit()
    conn.close()

def update_no_lottery(name, unit, contact_number, identity_note, space_id, car_id):
    conn = connect_db()
    cursor = conn.cursor()
    update_query = """
    UPDATE 免申請
    SET 姓名 = ? , 單位 = ? , 聯絡電話 = ? , 身分註記 = ?, 車位編號 = ?
    WHERE 車牌號碼 = ? 
    """
    cursor.execute(update_query, (name, unit, contact_number, identity_note, space_id, car_id))
    conn.commit()
    conn.close()

# 删除数据库中的记录
def delete_no_application(car_number):
    conn = connect_db()
    cursor = conn.cursor()
    delete_query = """
    DELETE FROM 免申請
    WHERE 車牌號碼 = ?
    """
    cursor.execute(delete_query, (car_number,))
    conn.commit()
    conn.close()

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

def delete_payment(period, name_code):
    conn = connect_db()
    cursor = conn.cursor()
    delete_query = """
    DELETE FROM 繳費紀錄
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

def new_no_application_payment(current, employee_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM 免申請繳費 WHERE 期別 = ? AND 姓名代號 = ?", (current, employee_id))
    output = cursor.fetchone()
    conn.commit()
    conn.close()
    return output is None

def new_payment_record(current, employee_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM 免申請繳費 WHERE 期別 = ? AND 姓名代號 = ?", (current, employee_id))
    output = cursor.fetchone()
    conn.commit()
    conn.close()
    return output is None

def exist_no_lottery(car_number):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM 免申請 WHERE 車牌號碼 = ?", (car_number,))
    output = cursor.fetchone()
    conn.commit()
    conn.close()
    return output is not None

def exist_lottery_payment(current, employee_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM 抽籤繳費 WHERE 期別 = ? AND 姓名代號 = ?", (current, employee_id))
    output = cursor.fetchone()
    conn.commit()
    conn.close()
    return output is not None

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

    # 新增数据库中的记录
def insert_no_application(current, employee_id, name, unit, car_number, contact_info, special_needs, place_id):
    conn = connect_db()
    cursor = conn.cursor()
    insert_query = """
    INSERT INTO 免申請 (期別,姓名代號,姓名,單位,車牌號碼,聯絡電話,身分註記,車位編號)
    VALUES (?,?,?,?,?,?,?,?)
    """
    cursor.execute(insert_query, (current, employee_id, name, unit, car_number, contact_info, special_needs, place_id))
    conn.commit()
    conn.close()

def insert_no_application_payment(current, employee_id, space_number):
    conn = connect_db()
    cursor = conn.cursor()
    insert_query = """
    INSERT INTO 免申請繳費 (期別,姓名代號,車位編號,繳費狀態)
    VALUES (?,?,?,'未繳費')
    """
    cursor.execute(insert_query, (current, employee_id, space_number))
    conn.commit()
    conn.close()

def insert_payment_record(current, employee_id, space_number):
    conn = connect_db()
    cursor = conn.cursor()
    insert_query = """
    INSERT INTO 繳費紀錄 (期別,姓名代號,車位編號)
    VALUES (?,?,?)
    """
    cursor.execute(insert_query, (current, employee_id, space_number))
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

def update_lottery_payment(car_id, payment_status, bill_number, current, employee_id):
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

def update_no_application_payment(car_id, payment_status, bill_number, current, employee_id):
    conn = connect_db()
    cursor = conn.cursor()
    update_query = """
    UPDATE 免申請繳費
    SET 車位編號 = ? , 繳費狀態 = ? , 發票號碼 = ?
    WHERE 期別 = ?  AND 姓名代號 = ?
    """
    cursor.execute(update_query, (car_id, payment_status, bill_number, current, employee_id))
    conn.commit()
    conn.close()

def update_confirm_parking(space_id, actual_current, employee_id):
    conn = connect_db()
    cursor = conn.cursor()
    update_query = """
    UPDATE 繳費紀錄
    SET 車位編號 = ? 
    WHERE 期別 = ? AND 姓名代號 = ? 
    """
    cursor.execute(update_query, (space_id, actual_current, employee_id))
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

# 設定有效的帳號和密碼
VALID_USERNAME = "admin"
VALID_PASSWORD = "password123"

# Session state 紀錄登入狀態
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False

# 簡單的登入函數
def login(username, password):
    if username == VALID_USERNAME and password == VALID_PASSWORD:
        st.session_state['logged_in'] = True
        st.success("登入成功!")
        time.sleep(2)
        st.rerun()
    else:
        st.error("帳號或密碼錯誤，請再試一次。")
        time.sleep(2)
        st.rerun()

# 若未登入，顯示登入表單
if not st.session_state['logged_in']:
    st.title("登入頁面")
    username = st.text_input("帳號")
    password = st.text_input("密碼", type="password")
    if st.button("登入"):
        login(username, password)

# 若已登入，顯示主頁內容
else:
    st.title("停車申請管理系統")
    # 创建选项卡
    tab1, tab2, tab4, tab5, tab6= st.tabs(["停車申請待審核", f"{current}停車申請一覽表", "保障停車分配車位", f"{current}員工停車繳費維護", "地下停車一覽表"])
    
    with tab1:
        st.header("停車申請待審核")
        df1 = load_data1()
        df1['通過'] = False
        df1['不通過'] = False
        editable_columns = ['通過', '不通過']
        disabled_columns = [col for col in df1.columns if col not in editable_columns]
        edited_df1 = st.data_editor(df1, disabled=disabled_columns)
    
        # 使用 session state 管理未通過的列表
        if 'not_passed_list' not in st.session_state:
            st.session_state.not_passed_list = []
        #測試中關閉寄信功能
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
                            #send_email(row['姓名代號'], row['姓名'], text, subject_text)
                            st.success("審核完成")
                        else:
                            subject_text = '本期停車申請文件審核通過通知'
                            text = '本期停車申請資料審核通過，謝謝您。'
                            #send_email(row['姓名代號'], row['姓名'], text, subject_text)
                            st.success("審核完成")
                        if row['身分註記'] != '一般':
                            insert_parking_fee(current, row['姓名代號'])
                    elif row['不通過']:
                        st.session_state.not_passed_list.append(row.to_dict())
            finally:
                upload_db(local_db_path, db_file_id)
                st.rerun()
    
        if st.session_state.not_passed_list:
            st.write("以下是審核不通過的申請，請確認是否確定不通過：")
            for i, record in enumerate(st.session_state.not_passed_list):
                if st.button(f"確認不通過 - {record['姓名']} ({record['車牌號碼']})", key=f"confirm_button_{i}"):
                    subject_text = '本期停車申請文件未審核通過通知'
                    text = '您申請的資料不符合停車要點規定，造成困擾敬請見諒。'
                    #send_email(record['姓名代號'], record['姓名'], text, subject_text)
                    delete_record(record['期別'], record['姓名代號'])
                    st.session_state.not_passed_list.pop(i)  # 移除已處理的記錄
                    st.success(f"審核不通過已確認 - {record['姓名']} ({record['車牌號碼']})")
                    upload_db(local_db_path, db_file_id)
                    st.rerun()  # 重新運行腳本，刷新頁面
    
    with tab2:
        st.header(f"{current}停車申請一覽表")
        name = st.text_input("請輸入要篩選的姓名", key="name_input_tab2") 
        df2 = load_data2(current)
        if name:
            df2 = df2[df2['姓名'].str.contains(name)]
        df2['更新資料'] = False
        df2['刪除資料'] = False
        editable_columns = ['車牌號碼','聯絡電話','更新資料','刪除資料']
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
                    st.rerun()  # 重新運行腳本，刷新頁面
                    
        with button2:
            if st.button('保障停車準備分配車位', key="prepare_parking_button"):
                try:
                    for index, row in edited_df2.iterrows():
                        if row['身分註記'] != '一般' and row['車牌綁定'] == True:
                            insert_parking_fee(row['期別'], row['姓名代號'])
                    st.success('免抽籤資料匯入成功')
                except:
                    st.error('本期免抽籤資料已經匯入進繳費表')
                finally:
                    upload_db(local_db_path, db_file_id)
                    st.rerun()  # 重新運行腳本，刷新頁面
    
        with button3:
            if st.button('更新確認', key="update_confirm_button"):
                try:
                    for index, row in edited_df2.iterrows():
                        if row['更新資料']:
                            update_application_record(row['期別'], row['姓名'], row['單位'], row['姓名代號'], row['車牌號碼'], row['聯絡電話'])
                    st.success('車牌更新成功')
                finally:
                    upload_db(local_db_path, db_file_id)
                    st.rerun()  # 重新運行腳本，刷新頁面
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
                st.rerun()  # 重新運行腳本，刷新頁面
    
        st.header("保障停車分配車位")
        df5 = load_data4(current)
        df5['分配車位'] = False
        editable_column = ['車位編號','分配車位']
        disabled_columns2 = [col for col in df5.columns if col not in editable_column]
    
        # 添加"是否重複車位"選項
        show_duplicate = st.checkbox('確認重複車位', key = 'df5')
    
        if show_duplicate:
            # 找出重複的車位編號
            duplicated_values = df5[df5.duplicated(subset='車位編號', keep=False)]
            df5 = duplicated_values
    
        edited_df5 = st.data_editor(
            df5,
            disabled=disabled_columns2
        )
    
        if st.button('分配車位確認'):
            try:
                for index, row in edited_df5.iterrows():
                    if row['分配車位']:
                        parking_distribution(row['車位編號'], row['期別'], row['姓名代號'])
                        st.success('車位分配成功')
            finally:
                upload_db(local_db_path, db_file_id)
                st.rerun()  # 重新運行腳本，刷新頁面
    with tab5:
        st.header(f"{current}員工停車繳費維護")
    
        # 姓名输入框
        name = st.text_input("請輸入要篩選的姓名", key="text_input_name_tab5")
    
        df6 = load_data5(current)
    
        # 篩選條件下拉選單
        filter_option1 = st.selectbox(
            "選擇車位篩選條件",
            ["所有", "正取", "備取"],
            key="filter_option1"
        )
        options = ['已繳費', '未繳費', '放棄']
        # 添加篩選條件選擇框
        filter_option2 = st.selectbox("篩選繳費狀態", ["所有"] + options, key="filter_option2")
    
        # 根據篩選條件過濾數據框
        if filter_option2 != "所有":
            df6 = df6[df6['繳費狀態'] == filter_option2]
    
        # 根據姓名篩選數據
        if name:
            df6 = df6[df6['姓名'].str.contains(name)]
    
        # 确保 '車位編號' 列为字符串，并填充 NaN 值
        df6['車位編號'] = df6['車位編號'].astype(str).fillna('')
    
        # 根據選擇的篩選條件進行進一步篩選
        if filter_option1 == "正取":
            df6 = df6[df6['車位編號'].str.startswith('B')]
        elif filter_option1 == "備取":
            df6 = df6[df6['車位編號'].str.startswith('備取')]
    
        # 添加"是否重複車位"選項
        show_duplicate = st.checkbox('確認重複車位', key = 'df6')
    
        if show_duplicate:
            # 找出重複的車位編號
            duplicated_values = df6[df6.duplicated(subset='車位編號', keep=False)]
            df6 = duplicated_values
    
        # 添加電子郵件列
        df6['電子郵件'] = df6['姓名代號'].apply(lambda x: f"u{x}@taipower.com.tw")
    
        df6['更新資訊'] = False
        editable_columns = ['車位編號', '車位備註', '繳費狀態', '發票號碼', '更新資訊']
        options = ['已繳費', '未繳費', '放棄', '轉讓']
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
            },
            key="data_editor_df6"
        )
    
        if st.button('更新資訊確認', key="update_info_button"):
            try:
                for index, row in edited_df6.iterrows():
                    if row['更新資訊']:
                        update_parking_note(row['車位編號'], row['車位備註'])
                        if exist_lottery_payment(current, row['姓名代號']):
                            if row['繳費狀態'] == '已繳費' and new_payment_record(current, row['姓名代號']):
                                update_lottery_payment(row['車位編號'], row['繳費狀態'], row['發票號碼'], current, row['姓名代號'])
                                insert_payment_record(current, row['姓名代號'], row['車位編號'])
                                st.success('資料更新成功')
                            else:
                                update_lottery_payment(row['車位編號'], row['繳費狀態'], row['發票號碼'], current, row['姓名代號'])
                                st.success('資料更新成功')
                        else:
                            update_no_application_payment(row['車位編號'], row['繳費狀態'], row['發票號碼'], current, row['姓名代號'])
                            update_no_lottery(row['姓名'], row['單位'], row['聯絡電話'], row['身分註記'], row['車位編號'], row['車牌號碼'])
                            st.success('資料更新成功')
            finally:
                upload_db(local_db_path, db_file_id)
                st.rerun()
    
        st.header(f"{current}地下停車場員工自用車停車名單")
    
        # 姓名输入框
        name = st.text_input("請輸入要篩選的姓名", key="text_input_name_df7")
    
        df7 = load_data6(current)
    
        # 根據姓名篩選數據
        if name:
            df7 = df7[df7['姓名'].str.contains(name)]
            # 添加"是否重複車位"選項
        
        show_duplicate = st.checkbox('確認重複車位', key = 'df7')
        if show_duplicate:
            # 找出重複的車位編號
            duplicated_values = df7[df7.duplicated(subset='車位編號', keep=False)]
            df7 = duplicated_values
    
        df7['刪除資訊'] = False
        editable_columns = ['刪除資訊']
        disabled_columns = [col for col in df7.columns if col not in editable_columns]
    
        edited_df7 = st.data_editor(
            df7,
            disabled=disabled_columns,
            key="data_editor_df7"
        )
    
        if 'delete_parking_list' not in st.session_state:
            st.session_state.delete_parking_list = []
    
        if st.button('刪除資料確認', key="delete_df7_button"):
            for index, row in edited_df7.iterrows():
                if row['刪除資訊']:
                    st.session_state.delete_parking_list.append(row.to_dict())
    
        if st.session_state.delete_parking_list:
            st.write("以下是選擇刪除的項目，請確認是否要刪除資料：")
            for i, row in enumerate(st.session_state.delete_parking_list):
                if st.button(f"確認刪除 - {row['姓名']} ({row['車牌號碼']})", key=f"confirm_delete_parking_button_{i}"):
                    st.session_state.delete_parking_list.pop(i)
                    if exist_no_lottery(row['車牌號碼']):
                        delete_no_application(row['車牌號碼'])
                    else:
                        delete_payment(current, row['姓名代號'])
                    st.success('資料刪除成功')
                    upload_db(local_db_path, db_file_id)
                    st.rerun()
        # 產生pdf，只保留'單位', '姓名', '車位編號'三欄
        df7_for_pdf = df7[df7['身分註記'].isin(['一般', '一般(轉讓)'])][['單位', '姓名', '車位編號']].copy()
        df7_for_pdf['姓名'] = df7_for_pdf['姓名'].apply(mask_name)  # 遮蔽姓名
    
        if st.button(f"產生{current}地下停車場員工自用車停車名冊電子檔"):
            pdf_file = convert_custom_df_to_pdf(df7_for_pdf)
            st.download_button(
                label="下載電子檔",
                data=pdf_file,
                file_name=f"{current}地下停車場員工自用車停車名冊.pdf",
                mime="application/pdf"
            )
    
    with tab6:
        st.header("地下停車一覽表")
        actual_quarter = get_actual_quarter(today.month)
        Taiwan_year = today.year - 1911
        actual_current = f"{Taiwan_year}{actual_quarter:02}"
    
        options1 = ["公務車", "公務車(電動)", "值班", "高階主管", "獨董", "公務保留", "身心障礙", "孕婦", "保障", "一般", "一般(轉讓)", "專案"]
        options2 = ["公務車", "公務車(電動)", "值班", "高階主管", "獨董", "公務保留", "身心障礙", "孕婦", "保障", "抽籤"]
    
        df7 = load_data7(actual_current)
        df7['更新資訊'] = False
        df7['刪除資訊'] = False
    
        name = st.text_input("請輸入要篩選的姓名", key="text_input_name_tab6")
        if name:
            df7['姓名'] = df7['姓名'].astype(str)  # 确保 '姓名' 列是字符串类型
            df7 = df7[df7['姓名'].str.contains(name)]
        filter_option = st.selectbox("篩選車位使用狀態", ["所有"] + options2, key="filter_option_tab6")
        if filter_option != "所有":
            df7 = df7[df7['使用狀態'] == filter_option]
            
        show_duplicate = st.checkbox('確認重複車位', key = 'df7-1')
        if show_duplicate:
            # 找出重複的車位編號
            duplicated_values = df7[df7.duplicated(subset='車位編號', keep=False)]
            df7 = duplicated_values
    
        uneditable_columns = ['姓名代號', '車牌號碼']
        disabled_columns = [col for col in df7.columns if col in uneditable_columns]
    
        edited_df7 = st.data_editor(
            df7,
            disabled=disabled_columns,
            column_config={
                "身分註記": st.column_config.SelectboxColumn(
                    "身分註記",
                    options=options1,
                    help="請選擇要調整的身分註記",
                    required=True
                ),
                "使用狀態": st.column_config.SelectboxColumn(
                    "使用狀態",
                    options=options2,
                    help="請選擇該車位用途",
                    required=True
                )
            },
            key="data_editor_df7_tab6"
        )
    
        button1, button2, button3 = st.columns(3)
    
        with button1:
            if st.button('彙整更新確認', key="update_button_tab6"):
                try:
                    for index, row in edited_df7.iterrows():
                        if row['更新資訊']:
                            update_parking_space(row['車位編號'], row['使用狀態'], row['車位備註'])
                            if exist_no_lottery(row['車牌號碼']):
                                update_no_lottery(row['姓名'], row['單位'], row['聯絡電話'], row['身分註記'], row['車位編號'], row['車牌號碼'])
                            else:
                                update_application_record(actual_current, row['姓名'], row['單位'], row['姓名代號'], row['車牌號碼'], row['聯絡電話'])
                                update_confirm_parking(row['車位編號'], actual_current, row['姓名代號'])
                    st.success('資料更新成功')
                finally:
                    upload_db(local_db_path, db_file_id)
                    st.rerun()
    
        with button2:
            if 'delete_data_list' not in st.session_state:
                st.session_state.delete_data_list = []
    
            if st.button('刪除資料確認', key="delete_button_tab6"):
                for index, row in edited_df7.iterrows():
                    if row['刪除資訊']:
                        st.session_state.delete_data_list.append(row.to_dict())
    
            if st.session_state.delete_data_list:
                st.write("以下是選擇刪除的項目，請確認是否要刪除資料：")
                for i, row in enumerate(st.session_state.delete_data_list):
                    if st.button(f"確認刪除 - {row['姓名']} ({row['車牌號碼']})", key=f"confirm_delete_button_tab6_{i}"):
                        st.session_state.delete_data_list.pop(i)
                        if exist_no_lottery(row['車牌號碼']):
                            delete_no_application(row['車牌號碼'])
                        else:
                            delete_payment(actual_current, row['姓名代號'])
                        st.success('資料刪除成功')
                        upload_db(local_db_path, db_file_id)
                        st.rerun()
    
        with button3:
            if st.button(f'{current}免申請停車進繳費表', key="payment_table_button"):
                try:
                    # 先从数据库中获取满足条件的 姓名代號 和 車位編號
                    conn = connect_db()
                    query = """
                    SELECT 姓名代號, 車位編號 
                    FROM 免申請 
                    WHERE 身分註記 IN ('高階主管', '值班')
                    """
                    df_high_level = pd.read_sql_query(query, conn)
                    conn.close()
    
                    # 对每一行数据执行 insert_no_application_payment 操作
                    for index, row in df_high_level.iterrows():
                        if new_no_application_payment(current, row['姓名代號']):
                            insert_no_application_payment(current, row['姓名代號'], row['車位編號'])
    
                    st.success(f'{current}免申請停車進繳費表成功')
    
                finally:
                    upload_db(local_db_path, db_file_id)
                    st.rerun()
    
        st.header("免申請停車資料新增")
        columns = ['期別', '姓名代號', '姓名', '單位', '車牌號碼', '聯絡電話', '身分註記', '車位編號']
        options = ["公務車", "公務車(電動)", "值班", "高階主管", "獨董", "公務保留", "孕婦", "一般(轉讓)", "專案"]
        df8 = pd.DataFrame(columns=columns)
        edited_df8 = st.data_editor(df8, num_rows="dynamic", column_config={
            "身分註記": st.column_config.SelectboxColumn(
                "身分註記",
                options=options,
                help="請選擇身分註記",
                required=True
            )
        }, key="data_editor_df8")
    
        if st.button('新增確認', key="insert_confirm_button"):
            for index, row in edited_df8.iterrows():
                try:
                    insert_no_application(row['期別'], row['姓名代號'], row['姓名'], row['單位'], row['車牌號碼'], row['聯絡電話'], row['身分註記'], row['車位編號'])
                    st.success("資料新增成功")
                except Exception as e:
                    st.error(f"資料新增失敗: {e}")
                finally:
                    upload_db(local_db_path, db_file_id)
                    st.rerun()
