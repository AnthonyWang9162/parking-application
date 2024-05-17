import streamlit as st
import sqlite3
import re
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 建立資料庫連接
conn = sqlite3.connect('parking_lot.db')
cursor = conn.cursor()

# 設置 Google Drive API 憑證
SCOPES = ['https://www.googleapis.com/auth/drive.file']
# 使用 Streamlit Secret 管理 Google Drive 憑證
SERVICE_ACCOUNT_INFO = st.secrets["gdrive_service_account"]
creds = service_account.Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=creds)

# 上傳檔案到指定的 Google 雲端硬碟資料夾
def upload_to_drive(file_path, filename, folder_id):
    media = MediaFileUpload(file_path, mimetype='application/octet-stream')
    file_metadata = {
        'name': filename,
        'parents': [folder_id]
    }
    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return file.get('id')

# 設置資料夾 ID
folder_id = st.secrets["folder_id"]  # 將資料夾 ID 放在 secrets 中

# 建立Streamlit表單
def main():
    st.title('停車抽籤申請表單')

    # 1. 單位
    unit = st.selectbox('(1)請問您所屬單位?', ['秘書處', '公眾服務處'])

    # 2. 大名
    name = st.text_input('(2)請問您的大名?')

    # 3. 愛車車號
    st.write('(3)請問您的愛車車號?')
    col1, col2, col3 = st.columns([1, 0.1, 1])
    with col1:
        car_number_prefix = st.text_input('前半段')
        if not re.match(r'^[A-Z0-9]+$', car_number_prefix):
            st.error('請輸入大寫英文字母和數字！')
    with col2:
        st.markdown('<h1 style="text-align: center;">-</h1>', unsafe_allow_html=True)
    with col3:
        car_number_suffix = st.text_input('後半段')
        if not re.match(r'^[A-Z0-9]+$', car_number_suffix):
            st.error('請輸入大寫英文字母和數字！')

    car_number = f"{car_number_prefix}-{car_number_suffix}"  # 合併車號

    # 4. 員工編號
    employee_id = st.text_input('(4)請問您的員工編號?')

    # 5. 特殊需求
    special_needs = st.selectbox('(5)請問是否有特殊需求？', ['一般', '孕婦', '身心障礙'])

    # 6. 連結資料
    proof_files = st.file_uploader('(6)請上傳證明文件照片', accept_multiple_files=True)

    # 7. 公務聯絡方式
    contact_info = st.text_input('(7)請問您的公務聯絡方式?')

    if st.button('提交'):
        # 檢查表單是否填寫完整
        if not unit or not name or not car_number or not employee_id or not special_needs or not proof_files or not contact_info:
            st.error('請填寫完整表單！')
        elif not re.match(r'^[A-Z0-9]+$', car_number_prefix) or not re.match(r'^[A-Z0-9]+$', car_number_suffix):
            st.error('您填寫的車號欄位有誤，請重新填寫')
        else:
            cursor.execute("SELECT * FROM 停車抽籤資料表 WHERE 員工編號 = ? AND 車號 = ? AND 申請身份= ?" , (employee_id, car_number, special_needs))
            existing_data = cursor.fetchone()
            # 已曾經審核通過資料直接自動審核成功
            if existing_data:
                cursor.execute("UPDATE 停車抽籤資料表 SET 單位=?,姓名=?,聯絡電話=?,本期申請車位 = ? WHERE 員工編號 = ? AND 車號 = ? AND 申請身份 = ?", (unit,name,contact_info,True,employee_id, car_number, special_needs))
                conn.commit()
                cursor.close()
                st.success('車位申請成功！')
            # 代表新申請需要審核
            else:
                cursor.execute("SELECT * FROM 審核停車申請表 WHERE 員工編號 = ? AND 車號 = ? AND 申請身份= ?" , (employee_id, car_number, special_needs))
                waiting_data = cursor.fetchone()
                #代表新申請人有資料異動
                if waiting_data:
                    for proof_file in proof_files:
                        # 將文件保存到暫存區
                        with open(proof_file.name, "wb") as f:
                            f.write(proof_file.getbuffer())
                        filename = f"{name}_{proof_file.name}"
                        upload_to_drive(proof_file.name, filename, folder_id)
                        os.remove(proof_file.name)  # 上傳後刪除本地文件
                    cursor.execute("UPDATE 審核停車申請表 SET 單位=?,姓名=?,聯絡電話=? WHERE 員工編號 = ? AND 車號 = ? AND 申請身份 = ?", (unit,name,contact_info,employee_id, car_number, special_needs))
                    conn.commit()
                    cursor.close()
                    st.success('車位申請修改成功！')
                else:
                    # 新增新的申請資料
                    insert_data(unit, name, car_number, employee_id , special_needs, proof_files, contact_info)
                    st.success('車位第一次申請成功！')

# 將填寫的資料插入到資料庫
def insert_data(unit, name, car_number, employee_id , special_needs, proof_files, contact_info):
    proof_data_list = []
    for proof_file in proof_files:
        # 將文件保存到暫存區
        with open(proof_file.name, "wb") as f:
            f.write(proof_file.getbuffer())
        filename = f"{name}_{proof_file.name}"
        upload_to_drive(proof_file.name, filename, folder_id)
        os.remove(proof_file.name)  # 上傳後刪除本地文件
        proof_data_list.append(proof_file.read())
    proof_data = ','.join(proof_data_list)  # 合併多個證明文件資料
    cursor.execute('''
    INSERT INTO 審核停車申請表 (員工編號,單位,姓名,車號,聯絡電話,申請身份,證明文件照片檔)
    VALUES (?,?,?,?,?,?,?)
    ''', (employee_id, unit, name, car_number, contact_info, special_needs, proof_data))
    conn.commit()
    cursor.close()

if __name__ == '__main__':
    main()
