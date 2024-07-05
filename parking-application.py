import streamlit as st
import pandas as pd

# 建立範例資料
data = {
    'Name': ['Alice', 'Bob', 'Charlie'],
    'Age': [30, 25, 35],
    'City': ['New York', 'San Francisco', 'Los Angeles']
}
df = pd.DataFrame(data)

# 使用st.experimental_data_editor顯示和編輯資料
st.title('Data Editor Example')
st.write('Use the data editor to view and edit the data.')

edited_df = st.experimental_data_editor(df)

# 顯示編輯後的資料
st.write('Edited Data:')
st.write(edited_df)
