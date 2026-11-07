from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
import pandas as pd
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException
import time
import os
import logging
import concurrent.futures

england_club_url = "https://find.englandfootball.com/"

delay = 10000
os.makedirs("logs", exist_ok=True)
os.makedirs("output", exist_ok=True)

def button_click_to_searching(driver, age, city):
    # Open the website
    driver.get(england_club_url)
    time.sleep(5)
    
    if len(driver.find_elements(By.ID, "onetrust-accept-btn-handler")) > 0:
        cookies_button = WebDriverWait(driver, delay).until(
            EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
        )
        cookies_button.click()

    # Start searching
    searching_button = WebDriverWait(driver, delay).until(
        EC.element_to_be_clickable((By.ID, "cta_start_searching_now"))
    )
    searching_button.click()
    
    search_people_element = WebDriverWait(driver, delay).until(
        EC.element_to_be_clickable((By.ID, "my_self"))
    )
    search_people_element.click()
    time.sleep(1)
    
    age_input_element = WebDriverWait(driver, delay).until(
        EC.element_to_be_clickable((By.ID, "selected_age"))
    )
    age_input_element.clear()
    age_input_element.send_keys(age)
    
    next_button_element = WebDriverWait(driver, delay).until(
        EC.element_to_be_clickable((By.ID, "onboarding_cta_next_question"))
    )
    next_button_element.click()
    
    football_button = WebDriverWait(driver, delay).until(
        EC.element_to_be_clickable((By.ID, "male_football"))
    )
    football_button.click()
    
    next_button_element = WebDriverWait(driver, delay).until(
        EC.element_to_be_clickable((By.ID, "onboarding_cta_next_question"))
    )
    next_button_element.click()
    
    club_football_button_element = WebDriverWait(driver, delay).until(
        EC.element_to_be_clickable((By.ID, "club_football"))
    )
    club_football_button_element.click()
    
    all_day_button_element = WebDriverWait(driver, delay).until(
        EC.element_to_be_clickable((By.ID, "alldays"))
    )
    all_day_button_element.click()
    
    disability_button_element = WebDriverWait(driver, delay).until(
        EC.element_to_be_clickable((By.ID, "disability_not_sure"))
    )
    disability_button_element.click()
    
    enter_post_code_button = WebDriverWait(driver, delay).until(
        EC.element_to_be_clickable((By.ID, "enter_postcode"))
    )
    enter_post_code_button.click()
    time.sleep(1)
    
    post_code_input = WebDriverWait(driver, delay).until(
        EC.element_to_be_clickable((By.ID, "searchBox"))
    )
    post_code_input.click()
    post_code_input.clear()
    post_code_input.send_keys(city + ", England")
    time.sleep(1)  
    post_code_input.send_keys(Keys.DOWN)
    
    time.sleep(2)
    
    # Click on the first option in the dropdown
    first_option = WebDriverWait(driver, delay).until(
        EC.visibility_of_element_located((By.CLASS_NAME, "line1"))
    )
    first_option.click()
    
    next_button_element = WebDriverWait(driver, delay).until(
        EC.element_to_be_clickable((By.ID, "onboarding_cta_next_question"))
    )
    next_button_element.click()
    time.sleep(10)


logging.basicConfig(filename='logs/crawling_log.log', level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')
city_df = pd.read_csv("output/england_city.csv")
contact_name_result = []
team_number_result = []
email_result = []
telephone_number_result = []
club_name_result = []
club_address_result = []
accredited_to_result = []
football_type_result = []
website_result = []

def scrape_city(city_index):
    try:
        chrome_options = webdriver.ChromeOptions()
        # chrome_options.add_argument("--headless")
        chrome_options.add_argument("--start-maximized")
        # chrome_options.add_argument('log-level=3')
        driver = webdriver.Chrome(options=chrome_options)
        
        rows = city_df.loc[city_index]
        
        for row in range(len(rows)):
            city = rows['name'].values[row]
        
            for age in range(30, 56, 5):
                button_click_to_searching(driver, age, city)
                logging.info("Button Clicked to search done.")
                logging.info(f"Current age: {age}")
                logging.info(f"Current City: {city}")
                
                print("Current age:", age)
                print("Current City:", city)
                print(f"City Index: {city_index}")

                if len(driver.find_elements(By.ID, "football_recommendations_result_wrapper")) > 0:
                    card_divs = WebDriverWait(driver, delay).until(
                                EC.visibility_of_element_located((By.ID, "football_recommendations_result_wrapper"))
                            )
                    cards = card_divs.find_elements(By.CLASS_NAME, "recommendationCard")
                    
                    length_of_cards = len(cards)
                    
                    for card in range(length_of_cards):
                        print(f"Finish card {card}")
                        logging.info(f"Finish card {card}")
                        try:
                            if len(driver.find_elements(By.CLASS_NAME, "css-1gkwtxd")) > 0:
                                if len(driver.find_elements(By.ID, f"recommended_football_type_cta_view_maps_of_clubs-{card + 1}")) > 0:
                                    football_club_finding = WebDriverWait(driver, delay).until(
                                        EC.visibility_of_element_located((By.ID, f"recommended_football_type_cta_view_maps_of_clubs-{card + 1}"))
                                    )
                                    
                                    football_club_finding.click()
                                    
                                    while True:
                                        try:
                                            load_more_element = "map_cta_load_more_recommendations"
                                            
                                            football_club_load_more = WebDriverWait(driver, 15).until(
                                                EC.visibility_of_element_located((By.ID, load_more_element))
                                            )
                                            
                                            time.sleep(1)                                 
                                            
                                            football_club_load_more.click()
                                            print("Load more card successfully")
                                            logging.info("Load more card successfully")

                                        except Exception:
                                            break

                                    if len(driver.find_elements(By.CLASS_NAME, "css-199032i")) > 0:
                                        try:
                                            club_length_element = WebDriverWait(driver, delay).until(
                                                EC.visibility_of_element_located((By.CLASS_NAME, "css-199032i"))
                                            )
                                            print("Get Club length successfully")
                                            logging.info("Get Club length successfully")
                                            if club_length_element:
                                                club_length_text = club_length_element.text.strip()
                                                if club_length_text:
                                                    club_length = int(club_length_text.split(" ")[0])
                                            
                                            for club in range(club_length):
                                                more_info_id = f"more_info-{club}"
                                                club_provider = f"cta_provider_club_card-{club}"                
                                                print("Get Club Provider successfully")
                                                logging.info("Get Club Provider successfully")
                                                try:
                                                    
                                                    if len(driver.find_elements(By.ID, club_provider)) > 0:
                                                        club_name = ""
                                                        
                                                        club_general_info_button = WebDriverWait(driver, delay).until(
                                                            EC.element_to_be_clickable((By.ID, club_provider))
                                                        )
                                                                        
                                                        club_general_info_button.click()
                                                        
                                                        club_info_button = WebDriverWait(driver, delay).until(
                                                            EC.element_to_be_clickable((By.ID, more_info_id))
                                                        )
                                                        action = ActionChains(driver)
                                                        
                                                        action.key_down(Keys.CONTROL).click(club_info_button).key_up(Keys.CONTROL).perform()
                                                        
                                                        if len(driver.window_handles) == 2:
                                                            driver.switch_to.window(driver.window_handles[1])
                                                        elif len(driver.window_handles) == 1:
                                                            time.sleep(2)
                                                            action.key_down(Keys.CONTROL).click(club_info_button).key_up(Keys.CONTROL).perform()
                                                            driver.switch_to.window(driver.window_handles[1])
                                                        
                                                        time.sleep(0.5)

                                                        
                                                        if len(driver.find_elements(By.ID, "club_name_heading")) > 0:
                                                            club_name_element = WebDriverWait(driver, delay).until(
                                                                EC.visibility_of_element_located((By.ID, "club_name_heading"))
                                                            )
                                                                                        
                                                            if club_name_element:
                                                                club_name = club_name_element.text
                                                        club_name_result.append(club_name)
                                                        club_address = ""
                                                        if len(driver.find_elements(By.CLASS_NAME, "css-86sf1o")) > 0:
                                                            club_address_element = WebDriverWait(driver, delay).until(
                                                                EC.visibility_of_element_located((By.CLASS_NAME, "css-86sf1o"))
                                                            )
                                                                                        
                                                            if club_address_element:
                                                                club_address = club_address_element.text
                                                        club_address_result.append(club_address)
                                                        accredited_to = ""
                                                        if len(driver.find_elements(By.CLASS_NAME, "css-o1e1ch")) > 0:
                                                            accredited_to_element = WebDriverWait(driver, delay).until(
                                                                EC.visibility_of_element_located((By.CLASS_NAME, "css-o1e1ch"))
                                                            )
                                                                                        
                                                            if accredited_to_element:
                                                                accredited_to = accredited_to_element.text
                                                        accredited_to_result.append(accredited_to)
                                                        football_types = []
                                                        football_type = ""
                                                        if len(driver.find_elements(By.CLASS_NAME, "css-ih6156")) > 0:
                                                            football_types_ul_element = WebDriverWait(driver, delay).until(
                                                                EC.visibility_of_element_located((By.CLASS_NAME, "css-ih6156"))
                                                            )
                                                                                        
                                                            football_types_li_elements = football_types_ul_element.find_elements(By.TAG_NAME, "li")
                                                            
                                                            football_types = [li.text.strip() for li in football_types_li_elements if li.text.strip()]
                                                            football_type = ", ".join(football_types)
                                                        football_type_result.append(football_type)
                                                        team_number = ""
                                                        if len(driver.find_elements(By.CLASS_NAME, "css-4682ps")) > 0:
                                                            team_number_element = WebDriverWait(driver, delay).until(
                                                                EC.visibility_of_element_located((By.CLASS_NAME, "css-4682ps"))
                                                            )
                                                                                        
                                                            team_number_text = team_number_element.text
                                                            if team_number_text:
                                                                team_number = team_number_text.split(" ")[0] if len(team_number_text) > 0 else "0"
                                                                
                                                        team_number_result.append(team_number)
                                                        contact_name = ""
                                                        if len(driver.find_elements(By.CLASS_NAME, "css-1gpgbx2")) > 0:                   
                                                            contact_name_element = WebDriverWait(driver, delay).until(
                                                                EC.visibility_of_element_located((By.CLASS_NAME, "css-1gpgbx2"))
                                                            )
                                                                                        
                                                            if contact_name_element:
                                                                contact_name = contact_name_element.text

                                                        contact_name_result.append(contact_name)
                                                        email = ""
                                                        telephone_number = ""
                                                        website = ""
                                                        if len(driver.find_elements(By.CLASS_NAME, "css-apgqqs")) > 0:
                                                            manager_info_div_element = WebDriverWait(driver, delay).until(
                                                                EC.visibility_of_element_located((By.CLASS_NAME, "css-apgqqs"))
                                                            )
                                                                                        
                                                            manager_info_ul = manager_info_div_element.find_element(By.TAG_NAME, "ul")
                                                            manager_info = manager_info_ul.text.split("\n")
                                                            
                                                            for info in manager_info:
                                                                if "@" in info and not email:
                                                                    email = info
                                                                elif info.startswith("0") and not telephone_number:
                                                                    telephone_number = info
                                                                elif not "@" in info and "." in info and not website:
                                                                    website = info
                                                        email_result.append(email)
                                                        telephone_number_result.append(telephone_number)
                                                        website_result.append(website)
                                                        print("Get Data successfully")
                                                        logging.info("Get Data successfully")
                                                        data = {
                                                            "Club Name": club_name_result,
                                                            "Address": club_address_result,
                                                            "Accredited To": accredited_to_result,
                                                            "Football Types": football_type_result,
                                                            "Team Numbers": team_number_result,
                                                            "Contact Name": contact_name_result,
                                                            "Email": email_result,
                                                            "Telephone Number": telephone_number_result,
                                                            "Website": website_result,
                                                        }


                                                        driver.close()
                                                        time.sleep(1)
                                                        driver.switch_to.window(driver.window_handles[0])
                                                        print("Done")
                                                        logging.info("Done")
                                                    
                                                except Exception as e4:
                                                    print("Error 4: " + str(e4))
                                                    logging.error("Error 4: " + str(e4))
                                                    break
                                            print("OK club Data")
                                            logging.info("OK club Data")
                                            new_df = pd.DataFrame(data)
                                            existing_df = pd.read_csv("club_data.csv")
                                            combined_df = pd.concat([existing_df, new_df])
                                            combined_df.drop_duplicates(subset=["Club Name"], inplace=True)
                                            combined_df.dropna(how="all", inplace=True)
                                            combined_df.to_csv("club_data.csv", index=False, mode="a", header=not os.path.exists("club_data.csv"))
                                            driver.back()
                                        except Exception as e3:
                                            print("Error 3: " + str(e3))
                                            logging.error("Error 3: " + str(e3))
                                            
                                            break
                                        # Remove Duplicated Data and nan data
                                        logging.info("Remove Duplicated Data and nan data")
                                        df = pd.read_csv("output/club_data.csv")
                                        df = df.dropna(how="all")
                                        df = df.drop_duplicates(subset=["Club Name"]).reset_index(drop=True)
                                        df.to_csv("output/club_data.csv", index=False)
                        except Exception as e2:
                            print("Error 2: " + str(e2))
                            logging.error("Error 2: " + str(e2))
                            
                            break
    except Exception as e1:
        print("Error 1: " + str(e1))
        logging.error("Error 1: " + str(e1))


def main():
    # Split the city DataFrame into chunks
    num_chunks = 10  # Adjust the number of chunks as needed
    chunk_size = len(city_df) // num_chunks
    city_indices_chunks = [city_df.index[i:i + chunk_size] for i in range(0, len(city_df), chunk_size)]

    # Iterate over each city chunk and start scraping
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_chunks) as executor:
        executor.map(scrape_city, city_indices_chunks)

if __name__ == "__main__":
    main()
