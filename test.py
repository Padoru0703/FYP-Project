from scraper_module import scrape_shopee_price

# Try something like 'GPU', 'Intel i5', or 'RTX 3060'
query = "RTX 3050"
result = scrape_shopee_price(query)

print("\n🔍 Result from Shopee:")
print(result)
