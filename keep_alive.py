from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager
import time

options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

# 修正這裡
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=options)

try:
    driver.get("https://parking-application0.streamlit.app/")
    time.sleep(10)  

    # 模擬點擊（可選）
    ActionChains(driver).move_by_offset(10, 10).click().perform()

    print("Successfully visited and clicked!")

except Exception as e:
    print(f"Error occurred: {e}")

finally:
    driver.quit()
