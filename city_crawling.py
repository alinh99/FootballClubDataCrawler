from bs4 import BeautifulSoup
import requests
import pandas as pd
import os

OUTPUT_FOLDER_NAME = "output"
os.makedirs(OUTPUT_FOLDER_NAME, exist_ok=True)

def get_data(url):
    url_request = requests.get(url)
    return url_request.text

city_result = {}  # Initialize an empty dictionary for city results

soup = BeautifulSoup(get_data("https://www.gov.uk/government/publications/list-of-cities/list-of-cities-html"), "html.parser")

city_names = list(soup.find("h4", {"id": "england"}).find_next().descendants)

cities = []

for city_name in city_names:
    city = city_name.text
    if '\n' in city_name:
        continue
    if '*' in city:
        city = city.replace("*", "")
    city_result = {"name": city}
    cities.append(city_result)

df = pd.DataFrame(cities)
df.drop_duplicates(inplace=True)
df.to_csv(f"{OUTPUT_FOLDER_NAME}/england_city.csv", index=False)
print(f"Saved {len(df)} cities to {OUTPUT_FOLDER_NAME}/england_city.csv")