#economic_calender_scraper.py
import json
import os
import asyncio
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
#import subprocess

#chrome_version = subprocess.run(
    #['chrome', '--version'], capture_output=True, text=True).stdout
#print(f"[economic_calender_scraper.py] Chrome version: {chrome_version}")

#driver_version = subprocess.run(
    #['chromedriver', '--version'], capture_output=True, text=True).stdout
#print(f"[economic_calender_scraper.py] ChromeDriver version: {driver_version}")

# Initialize the WebDriver with options to suppress SSL errors
options = webdriver.ChromeOptions()
options.add_argument('--ignore-certificate-errors')
options.add_argument('--ignore-ssl-errors')
options.add_argument('--allow-insecure-localhost')

async def get_economic_calendar_data(i_timespan, star_ammount, world_type):
    #Set 'driver_version' to whatever driver version you have on install
    # Initialize the WebDriver without specifying a version
    service = ChromeService(ChromeDriverManager().install())  # Automatically install the correct version
    driver = webdriver.Chrome(service=service, options=options)
    # driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    driver.get("https://tradingeconomics.com/calendar")
    # Other code...
    # Wait for the page to load and the date picker to be available
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//*[@id='aspnetForm']/div[3]/div/div/table/tbody/tr/td[1]/div/div[1]/button")))

    # Set the date type to 'This Week'
    date_picker = driver.find_element(By.XPATH, "//*[@id='aspnetForm']/div[3]/div/div/table/tbody/tr/td[1]/div/div[1]/button")
    date_picker.click()
    await asyncio.sleep(1)  # Allow the dropdown to open
    if i_timespan == "recent":
        timespan =    "//*[@id='aspnetForm']/div[3]/div/div/table/tbody/tr/td[1]/div/div[1]/ul/li[1]/a"
    elif i_timespan == "today":
        timespan =     "//*[@id='aspnetForm']/div[3]/div/div/table/tbody/tr/td[1]/div/div[1]/ul/li[2]/a"
    elif i_timespan == "week":
        timespan = "//*[@id='aspnetForm']/div[3]/div/div/table/tbody/tr/td[1]/div/div[1]/ul/li[4]/a"
    date_option_type = driver.find_element(By.XPATH, timespan)
    date_option_type.click()

    # Set the impact to three stars
    impact_dropdown = driver.find_element(By.XPATH, "//*[@id='aspnetForm']/div[3]/div/div/table/tbody/tr/td[1]/div/div[2]/button")
    impact_dropdown.click()
    await asyncio.sleep(1)
    if star_ammount == 1:
        star_xpath =  "//*[@id='aspnetForm']/div[3]/div/div/table/tbody/tr/td[1]/div/div[2]/ul/li[1]/a"
    elif star_ammount == 2:
        star_xpath =  "//*[@id='aspnetForm']/div[3]/div/div/table/tbody/tr/td[1]/div/div[2]/ul/li[2]/a"
    elif star_ammount == 3:
        star_xpath = "//*[@id='aspnetForm']/div[3]/div/div/table/tbody/tr/td[1]/div/div[2]/ul/li[3]/a"
    star_type = driver.find_element(By.XPATH, star_xpath)
    star_type.click()

    # Set the country type to 'America'
    world_section_dropdown = driver.find_element(By.XPATH, "//*[@id='aspnetForm']/div[3]/div/div/table/tbody/tr/td[1]/div/button")
    world_section_dropdown.click()
    await asyncio.sleep(1)  # Allow the dropdown to open
    if world_type == "all":
        world_xpath = "//*[@id='te-c-main-countries']/div/div[1]/span[1]"
    elif world_type == "major":
        world_xpath = "//*[@id='te-c-main-countries']/div/div[1]/span[2]"
    elif world_type == "africa":
        world_xpath = "//*[@id='te-c-main-countries']/div/div[1]/span[3]"
    elif world_type == "america":
        world_xpath = "//*[@id='te-c-main-countries']/div/div[1]/span[4]"
    elif world_type == "asia":
        world_xpath = "//*[@id='te-c-main-countries']/div/div[1]/span[5]"
    elif world_type == "europe":
        world_xpath = "//*[@id='te-c-main-countries']/div/div[1]/span[6]"
    world_option = driver.find_element(By.XPATH, world_xpath)
    world_option.click()
    # Click save button
    save_button = driver.find_element(By.XPATH, "//*[@id='te-c-main-countries']/div/div[2]/div[3]/a/i")
    save_button.click()

    # Set event type to 'All Events'
    event_type_dropdown = driver.find_element(By.XPATH, "//*[@id='aspnetForm']/div[3]/div/div/table/tbody/tr/td[1]/div/div[3]/button")
    event_type_dropdown.click()
    await asyncio.sleep(1)  # Allow the dropdown to open
    all_events_option = driver.find_element(By.XPATH, "//*[@id='aspnetForm']/div[3]/div/div/table/tbody/tr/td[1]/div/div[3]/ul/li[1]/a")
    all_events_option.click()

    # Set UTC to -5
    utc_dropdown = driver.find_element(By.XPATH, "//*[@id='aspnetForm']/div[3]/div/div/table/tbody/tr/td[1]/div/div[4]/div")
    utc_dropdown.click()
    await asyncio.sleep(1)  # Allow the dropdown to open
    utc_minus_5 = driver.find_element(By.XPATH, "//*[@id='DropDownListTimezone']/option[8]")
    utc_minus_5.click()

    # Wait for the page to refresh and the table to be available
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "calendar")))

    # Extract data from the table
    data = {}
    calendar_table = driver.find_element(By.ID, "calendar")
    date_headers = calendar_table.find_elements(By.CLASS_NAME, "table-header")

    for header in date_headers:
        try:
            # This is where we get the "Tuesday June 25 2024"
            date_text = header.find_element(By.XPATH, ".//th[@colspan='3']").text.strip()
            print(f"Date: {date_text}")
            if date_text:
                # Convert the date from "Tuesday June 25 2024" to "06-25-24"
                date_obj = datetime.strptime(date_text, "%A %B %d %Y")
                formatted_date = date_obj.strftime("%m-%d-%y")
                print(f"Formatted Date: {formatted_date}")
                current_date = formatted_date
                if current_date not in data:
                    data[current_date] = {}

            # Find the tbody following the current header
            tbody = header.find_element(By.XPATH, "following-sibling::tbody")
            event_rows = tbody.find_elements(By.XPATH, ".//tr")
            print(f"num of events: {len(event_rows)}")
            
            for event_row in event_rows:
                try:
                    time_td = event_row.find_element(By.XPATH, "./td[1]/span")
                    event_td = event_row.find_element(By.XPATH, "./td[3]/a")
                    if current_date and time_td and event_td:
                        _time = time_td.text.strip()
                        event = event_td.text.strip()
                        if _time not in data[current_date]:
                            data[current_date][_time] = []
                        data[current_date][_time].append(event)
                except Exception as e:
                    print(f"Error processing event_row: {e}")
                    continue
        
        except Exception as e:
            print(f"Error processing row: {e}")
            continue

    driver.quit()

    if i_timespan == "today":
        timespan_label = f"{(datetime.now()).strftime('%m-%d-%y')}"
    elif i_timespan == "week" or i_timespan == "recent":
        timespan_label = f"{(datetime.now() - timedelta(days=datetime.now().weekday())).strftime('%m-%d-%y')} to {(datetime.now() + timedelta(days=6-datetime.now().weekday())).strftime('%m-%d-%y')}"
    
    final_data = {
        f"{i_timespan}_timespan": timespan_label,
        "dates": data
    }

    JSON_FILE = f'{i_timespan}_ecom_calender.json'
    if not os.path.exists(JSON_FILE):
        open(JSON_FILE, 'w').close()

    with open(JSON_FILE, 'w') as f:
        json.dump(final_data, f, indent=4)

    print(f"Data saved to {JSON_FILE}")

def check_order_time_to_event_time(time_threshold=20, json_file='week_ecom_calender.json'):
    
    # Ensure the JSON file exists
    if not os.path.exists(json_file):
        raise FileNotFoundError(f"{json_file} does not exist")

    # Read the JSON data
    with open(json_file, 'r') as file:
        data = json.load(file)

    # Extract today's date in the format "mm-dd-yy"
    today_date = datetime.now().strftime('%m-%d-%y')

    # Check if there are events for today
    if today_date not in data['dates']:
        print("No Events today")
        return True  # No events today

    # Get the list of events for today
    events_today = data['dates'][today_date]
    print(f"Event(s): {events_today}")

    # Get and convert the current time to a datetime object for comparison
    current_time = datetime.now().strftime("%I:%M %p")
    current_time_obj = datetime.strptime(current_time, "%I:%M %p")
    print(f"Current Time: {current_time_obj}")
    # Check each event time
    for event_time_str in events_today:
        event_time_obj = datetime.strptime(event_time_str, "%I:%M %p")
        
        # Calculate the time difference
        time_diff = (event_time_obj - current_time_obj).total_seconds() / 60

        # Check if the current time is within the threshold before the event
        if 0 <= time_diff <= time_threshold:
            return False  # Within the threshold before an event

    return True  # No events within the threshold

def setup_economic_news_message(json_file='week_ecom_calender.json'):
    # Ensure the JSON file exists
    if not os.path.exists(json_file):
        raise FileNotFoundError(f"{json_file} does not exist")

    # Read the JSON data
    with open(json_file, 'r') as file:
        data = json.load(file)

    # Extract today's date in the format "mm-dd-yy"
    today_date = datetime.now().strftime('%m-%d-%y')

    # Check if there are events for today
    if today_date not in data['dates']:
        return f"""
**NO MAJOR NEWS EVENTS TODAY**
"""

    # Get the list of events for today
    events_today = data['dates'][today_date]

    # Generate the message
    message = f"""
**TODAYS MAJOR ECONOMIC NEWS**
-----
"""

    for event_time, events in events_today.items():
        message += f"**{event_time}**\n"
        for event in events:
            message += f"- {event}\n"
        message += "\n"  # Add an extra newline for separation between event times

    return message.strip()


# Example usage in an asynchronous context
async def main():
    await get_economic_calendar_data("week", 3, "america")

if __name__ == "__main__":
    asyncio.run(main()) 