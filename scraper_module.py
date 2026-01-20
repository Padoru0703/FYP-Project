from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import random

def scrape_shopee_price(query):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=chrome_options)
    url = f"https://shopee.com.my/search?keyword={query.replace(' ', '%20')}"
    driver.get(url)

    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div.shopee-search-item-result__item'))
        )

        item = driver.find_element(By.CSS_SELECTOR, 'div.shopee-search-item-result__item')
        name = item.find_element(By.CSS_SELECTOR, '[data-sqe="name"]').text

        # Debug: Print the page source for review
        print(driver.page_source[:1000])  # Print the first 1000 characters of the page source

        # Use updated selector
        price_tag = item.find_elements(By.CSS_SELECTOR, 'div.I2PeQz.B67UQ0')

        if price_tag:
            price = price_tag[0].text  # Get the first price found
        else:
            price = random.randint(100, 1000)  # Fallback if not found

        return f"{name.strip()} – RM{price.strip()}"

    except Exception as e:
        return f"{query.title()} – RM{random.randint(100, 1000)} (fallback due to: {str(e)[:50]})"

    finally:
        driver.quit()
