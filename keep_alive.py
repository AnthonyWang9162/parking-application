from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager
import time
import os

# 設定瀏覽器為無頭模式（headless）
options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

# 建立瀏覽器驅動
driver = webdriver.Chrome(ChromeDriverManager().install(), options=options)

try:
    # 更換成你的 Streamlit 網址
    driver.get("https://parking-application0.streamlit.app/")
    time.sleep(10)  # 等待網頁載入完成

    # 以下為模擬用戶互動的範例（點擊某按鈕或畫面任意處）
    # 若無特殊需求，可省略模擬點擊動作
    ActionChains(driver).move_by_offset(10, 10).click().perform()
k
    print("Successfully visited and clicked!")
    
except Exception as e:
    print(f"Error occurred: {e}")

finally:
    driver.quit()
