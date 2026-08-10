import requests as Requests
from bs4 import BeautifulSoup
import time
import threading
import sqlite3
import math
import logging
import os
import pandas
from fake_useragent import UserAgent
from requests_ip_rotator import ApiGateway, EXTRA_REGIONS
from queue import Queue
from tkinter import *

global headers

search_page_url = "https://www.bloodhorse.com/stallion-register/Results/ResultsTable?ReferenceNumber=0&Page="
url_addition = "&IncludePrivateFees=False"
url_base = "https://www.bloodhorse.com"

# Set this to true if you want to set links by default (Update: shouldn't matter, set in GUI)
global set_horse_links
set_horse_links=False

logging.basicConfig(filename="webscraper.log", level=logging.INFO, format='%(levelname)-8s - %(message)s\n-[%(filename)s:%(lineno)d]')

# Set the headers to be used when making a request
def Header_Select(failures):
    
    # Previously there was a list of headers that we would select from.
    # This variable is, as of now, unneeded, but if it's needed we have it.
    select_number = failures

    # With most random user agents we appear like a normal user
    headers = {
        'user-agent' :  UserAgent(platforms=['pc']).random,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Referer": "https://www.bloodhorse.com/stallion-register/",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9"
    }

    return headers

headers = Header_Select(0)

# Step 1: Store the links for each horse's Bloodhorse page from their search index.
# Step 2: From each Bloodhorse page, we get the link to Equineline
# Step 2.5: We save the links used to save time in the future
# Step 3: We get the Equineline document and save its data to the SQLite database

# Comb the search page from Bloodhorse to get links to all the horses
def Bloodhorse_Get(starting_page_num, thread_num, out_q, accessKeyID, accessKeySecret, page_range, args):
    global set_horse_links

    logging.info("Thread " + str(thread_num) + " Starting on Bloodhorse page: " + str(starting_page_num))

    link_list = []
    
    if set_horse_links:
        global headers
        
        bloodhorse_failures = 0
        
        
        pagenum=starting_page_num
        
        all_links_added = False

        gateway = ApiGateway("https://www.bloodhorse.com", access_key_id=accessKeyID, access_key_secret=accessKeySecret)
        gateway.start()


        session = Requests.Session()
        session.mount("https://www.bloodhorse.com",gateway)

        connecting_url = search_page_url + str(pagenum) + url_addition
        while pagenum <= starting_page_num + page_range and not all_links_added and bloodhorse_failures <= max_errors:
            
            # logging.debug(f"THREAD {thread_num} Connecting to Bloodhorse; attempt #"+str(bloodhorse_failures +1) + "\nshould be page #"+str(pagenum+1))

            time.sleep(request_delay)

            bloodhorse_response = session.post(connecting_url, headers=headers)

            bloodhorse_text = bloodhorse_response.text

            bloodhorse_data = BeautifulSoup(bloodhorse_text, "html.parser")
            
            horse_link_divs = bloodhorse_data.find_all("a", recursive=True)
            
            next_page = bloodhorse_data.find("a", attrs={"class":"next"}, recursive=True)


            temp_url_copy = connecting_url
            
                    
            try:
                # Attempting to create this test_url will give an index failure if we haven't found the next page link
                # Which is how I test for a successful connection
                test_url = url_base + str(next_page).split('href="')[1].split('">')[0].replace("amp;", "")
                pagenum += 1

                connecting_url = search_page_url + str(pagenum) + url_addition

                logging.info("Thread " + str(thread_num) + " Will connect to " + connecting_url +" next.")
            except IndexError:
                logging.error("Thread " + str(thread_num) + ": Error getting next page; trying with new headers")
                bloodhorse_failures += 1
                headers = Header_Select(bloodhorse_failures)
            
            is_last_page = bloodhorse_data.find("a", attrs={"class":"next disabled"})
            if is_last_page != None:
                all_links_added = True
            
            if connecting_url != temp_url_copy:
                for element in horse_link_divs:
                    if "/stallion-register/stallions/" in str(element) and "class" not in str(element):
                        link = url_base + str(element).split('href="')[1].split('">')[0]
                        if link not in link_list:
                            link_list.append(link)

            if bloodhorse_failures >= max_errors:
                logging.error("Thread " + str(thread_num) + " Unable to progress. (Max attempts reached)")

    if len(link_list) > 0:
        for i in range(len(link_list) -1):
            sqlInsertRowString = " INSERT OR IGNORE INTO HORSES (BH_link) VALUES (?); "
            sqlInsertRowValue = (link_list[i],)

            out_q.put((sqlInsertRowString, sqlInsertRowValue,))

    logging.info("Thread " + str(thread_num) + " sent sentinel from Bloodhorse_Get()")
    out_q.put(sentinel)

# Get the Equineline links from each horse's Bloodhorse page
def Bloodhorse_Find_Equineline(starting_index, thread_num, out_q, accessKeyID, accessKeySecret, index_range, bhorse_link_list):
    global headers
    global set_horse_links

    bloodhorse_failures = 0

    gateway = ApiGateway("https://www.bloodhorse.com", access_key_id=accessKeyID, access_key_secret=accessKeySecret)
    gateway.start()


    session = Requests.Session()
    session.mount("https://www.bloodhorse.com",gateway)
    
    counter_index=starting_index
    
    if set_horse_links:
        while counter_index <= starting_index + index_range:
            if counter_index >= len(bhorse_link_list):
                logging.info("Breaking thread: " + str(thread_num) + " (Completed list)")
                break

            link = bhorse_link_list[counter_index]
            #logging.debug("Fetching Equineline link from "+link+" on thread #"+str(thread_num))

            time.sleep(request_delay)

            bloodhorse_response = session.post(link, headers=headers)

            bloodhorse_text = bloodhorse_response.text

            bloodhorse_data = BeautifulSoup(bloodhorse_text, "html.parser")
                
            equineline_link_element = str(bloodhorse_data.find("a", attrs={"class":"equineline", "target":"_blank"}, recursive=True))

            try:
                # The equineline page by default doesn't have the plaintext, but by modifying the link we can get to the page that does
                equineline_link = equineline_link_element.split('href="')[1].split('" class')[0].replace("amp;", "").replace("bh.cfm?", "bh_main.cfm?").split(" ")[0]
                counter_index +=1
            except AttributeError:
                logging.error(f"Error getting equineline link (Thread #{thread_num}); trying with next headers")
                bloodhorse_failures += 1
                headers = Header_Select(bloodhorse_failures)
            except Exception as exception:

                # It's possible that an unpredicted error occurs at a link, in which case we should skip it
                if str(exception) is not str(AttributeError):
                    if str(exception) != "list index out of range":
                        logging.error("-"*thread_num +"THREAD #"+str(thread_num)+" Unhandled Error: "+str(exception))
                    else:
                        logging.info("Equineline not found at: " + link)
                    equineline_link = "ERROR"
                    counter_index +=1

            sqlUpdateString = " UPDATE HORSES SET EQ_link = ? WHERE BH_link IS ?; "
            sqlUpdateValue = (equineline_link, link,)

            out_q.put((sqlUpdateString,sqlUpdateValue,))

            if bloodhorse_failures >= max_errors:
                counter_index +=1
                bloodhorse_failures = 0

    logging.info("Thread " + str(thread_num) + " sent sentinel from Bloodhorse_Find_Equineline()")
    out_q.put(sentinel)

# Fetch and add data from Equineline to the SQLite database
def Equineline_Get(starting_index, thread_num, out_q, accessKeyID, accessKeySecret, index_range, eq_link_list):
    global headers

    # The data is split by lines, so to adjust this find the line with the data you need
    # and find how many lines down it is, with the top line being zero (the empty lines DO COUNT)
    # then use that number instead of the first number in the list.
    # The data is then split on the " " characters (removing extra), so "hello world" becomes [hello,world]
    # to adjust these, find how many across your data is, and use that number instead of the second number. 
    # The third one is for additional formatting. If you aren't sure if you need it, remove it.
    name_index      =   [2, -1, 1]
    crops_index     =   [5, 0]
    foals_index     =   [6, 0]
    RA_foals_index  =   [24, 4]
    winners_index   =   [26, 4, 0]
    b_winners_index =   [28, 3, 0]
    starters_index  =   [25, 3, 0]
    wins_index      =   [32, 2, 0]
    starts_index    =   [31, 1]
    earnings_index  =   [35, 1, 1]
    weanlings_index =   [60, 1]
    Wean_sales_index=   [60, 2, 1]
    yearlings_index =   [61, 1]
    Year_sales_index=   [61, 2, 1]


    equineline_failures = 0

    gateway = ApiGateway("http://www.equineline.com", access_key_id=accessKeyID, access_key_secret=accessKeySecret)
    gateway.start()


    session = Requests.Session()
    session.mount("http://www.equineline.com",gateway)
    
    counter_index=0
    while counter_index <= starting_index + index_range:

        if counter_index >= len(eq_link_list):
            logging.info("Breaking thread: " + str(thread_num) + " (Completed list)")
            break

        link = eq_link_list[counter_index]
        time.sleep(request_delay)

        equineline_response = session.get(link, headers=headers)

        equineline_text = equineline_response.text
        equineline_data = BeautifulSoup(equineline_text, "html.parser")

        data = equineline_data.find_all("pre", recursive=True)


        
        try:
            page_one = data[0].contents[0]
            page_two = data[1].contents[0]

            horse_data = (page_one + "\n" + page_two).splitlines()

            # Until Equineline changes their data format, we know where each piece is stored (it's a <pre>)
            # Extra steps for the name since many have multiple words
            name_list = horse_data[name_index[0]].split(" ")
            start_name = False
            name = ''

            for word in name_list:
                
                if start_name:
                    name += word + " "
                if word == 'of':
                    start_name = True
            
            # Certain horses will have an = in their name, this checks for that and removes it
            name          = name.strip()[:name_index[1]][name_index[2]:] if name.strip()[:name_index[1]][0] == '=' else name.strip()[:name_index[1]]
            crops         = [data for data in horse_data[crops_index[0]].split(" ") if data != ''][crops_index[1]]
            foals         = [data for data in horse_data[foals_index[0]].split(" ") if data != ''][foals_index[1]]
            RA_foals      = [data for data in horse_data[RA_foals_index[0]].split(" ") if data != ''][RA_foals_index[1]]
            winners       = [data for data in horse_data[winners_index[0]].split(" ") if data != ''][winners_index[1]].split("(")[winners_index[2]]
            b_winners     = [data for data in horse_data[b_winners_index[0]].split(" ") if data != ''][b_winners_index[1]].split("(")[b_winners_index[2]]
            starters      = [data for data in horse_data[starters_index[0]].split(" ") if data != ''][starters_index[1]].split("(")[starters_index[2]]
            wins          = [data for data in horse_data[wins_index[0]].split(" ") if data != ''][wins_index[1]].split("(")[wins_index[2]]
            starts        = [data for data in horse_data[starts_index[0]].split(" ") if data != ''][starts_index[1]]
            earnings      = [data for data in horse_data[earnings_index[0]].split(" ") if data !=''][earnings_index[1]][earnings_index[2]:]
            num_weanlings = [data for data in horse_data[weanlings_index[0]].split(" ") if data !=''][weanlings_index[1]]
            sale_weanling = [data for data in horse_data[Wean_sales_index[0]].split(" ") if data !=''][Wean_sales_index[1]][Wean_sales_index[2]:]
            num_yearlings = [data for data in horse_data[yearlings_index[0]].split(" ") if data !=''][yearlings_index[1]]
            sale_yearling = [data for data in horse_data[Year_sales_index[0]].split(" ") if data !=''][Year_sales_index[1]][Year_sales_index[2]:]

            # Add data to SQLite database
            sqlUpdateString = """ UPDATE HORSES SET 
                                Name = ?, 
                                Crops = ?,
                                Foals = ?,
                                RA_Foals = ?,
                                Winners = ?,
                                Winners_B = ?,
                                Wins = ?,
                                Starters = ?,
                                Starts = ?,
                                Earnings = ?,
                                Num_Weanlings = ?,
                                Sales_Weanlings = ?,
                                Num_Yearlings = ?,
                                Sales_Yearlings = ?
                                WHERE EQ_link = ?; """ 
            sqlUpdateValues = (name, 
                                crops, 
                                foals, 
                                RA_foals, 
                                winners, 
                                b_winners, 
                                wins, 
                                starters,
                                starts,
                                earnings,
                                num_weanlings,
                                sale_weanling,
                                num_yearlings,
                                sale_yearling,
                                str(link),)
            
            out_q.put((sqlUpdateString, sqlUpdateValues,))
            counter_index +=1

        except Exception as e:
            equineline_failures += 1
            logging.error(("-"*thread_num) + "ERROR ON THREAD "+ str(thread_num) +":\n"+str(e)+"\nTrying with new headers, " + str(max_errors - equineline_failures) + " tries until moving on")
            headers = Header_Select(equineline_failures)
            

        if equineline_failures >= max_errors:
            counter_index +=1
            equineline_failures = 0

    logging.info("Thread " + str(thread_num) + " sent sentinel from Equineline_Get()")
    out_q.put(sentinel)

# Execute SQL commands from the queue
def Process_SQL_Commands(in_q, thread_count):

    sqlconnection = sqlite3.connect("horses.db")
    sqlcursor = sqlconnection.cursor()

    sentinel_count = 0

    while True:
        command = in_q.get()

        if command == "////":
            sentinel_count +=1
        else:
            try:
                sqlCommand =  command[0]
                sqlValues = command[1]
                sqlcursor.execute(sqlCommand, sqlValues)
            except Exception as e:
                logging.error("Error with SQL execution:\nSQL:\n" + str(sqlCommand) +"\n"+ str(sqlValues) +"\nError:\n"+str(e))
                os._exit(1)


        in_q.task_done()
        
        if sentinel_count == thread_count and in_q.qsize() == 0:
            logging.info("Queue emptied.")
            sqlcursor.close()
            break

    sqlconnection.commit()

# This can be any unique identifier as long as Process_SQL_Commands() increases sentinel_count when received
sentinel = "////"


def Start_Threads(threadcount, taskcount, accessID, accessKey, target_function, param=None):
    created_thread_list = []

    q = Queue()
    queue_processor = threading.Thread(target=Process_SQL_Commands, args=(q, threadcount, ))
    queue_processor.start()


    # Divides the number of pages as equally as possible among the chosen number of threads.
    tasks_per_thread = math.floor(taskcount / threadcount)

    # Shows how many pages are left over.
    remainder_tasks = taskcount % threadcount

    # If a thread is assigned additional pages, this variable updates the starting point for the other threads
    carry = 0
    # These two variables are (hopefully) for readability
    count_from_first = 1
    include_endpoint = 1

    for threadnum in range(threadcount):
        start= (threadnum*tasks_per_thread) + carry + (count_from_first if target_function == Bloodhorse_Get else 0)

        # Assign the remainder to a thread (and decrease the remaining remainder)
        if threadnum > threadcount - remainder_tasks-1 and remainder_tasks > 0:
            carry += 1
            remainder_tasks -= 1
        
        end = (threadnum+1) * tasks_per_thread + carry

        # Find the number of pages each thread takes care of
        p_range = end + include_endpoint - start

        # Create thread
        thread = threading.Thread(target=target_function, args=(start, threadnum, q, accessID, accessKey, p_range, param, ))
        
        # Add to list of threads (in case needed later)
        created_thread_list.append(thread)

    for thread in created_thread_list:
        thread.start()

    for thread in created_thread_list:
        thread.join()

    q.join()

    queue_processor.join()
    
    logging.debug(str(threadcount) + " Threads finished.")

    
# TKinter App
class App(Tk):

    def __init__(self):
        Tk.__init__(self)
        
        # Window Title
        self.title("Bloodhorse and Equineline Scraper")
        
        # Window Size
        self.geometry('800x250')

            
        self.AWS_SECRET = ''
        self.AWS_ID = ''
        self.pages = 0

        # Option to create a file with links to horses that had issues
        self.unfound_horse_file = BooleanVar()
        self.uhorse_file = Checkbutton(self, variable=self.unfound_horse_file, onvalue=True, offvalue=False)
        self.uhorse_file.grid(column=1,row=1)
        self.uhorse_lbl = Label(self, text="Create file with unfound horses?")
        self.uhorse_lbl.grid(column=0,row=1)


        # First label, also becomes "running" when running
        self.lbl = Label(self, text="Update Bloodhorse Links?")
        self.lbl.grid(row=0, column=0)

        # User chosen thread count display
        self.thcount = IntVar(value=1)
        self.lbl_thcount = Label(self, text='Thread Count: ' + str(self.thcount.get()))
        self.lbl_thcount.grid(column=0,row=2)

        # Checkbox for whether to update links
        self.linkupdatevar = BooleanVar()
        self.linkupdate = Checkbutton(self, variable=self.linkupdatevar,onvalue=True, offvalue=False)
        self.linkupdate.grid(column=1,row=0)

        # Start Button
        self.btn_start = Button(self, text = 'Start',
            fg= 'red', command=self.start_clicked)
        self.btn_start.grid(column=5,row=6)
    
        # Thread Count Selection Menu
        self.thcountMenu = Menubutton(self, text="-> Select Thread Count")

        self.menu = Menu(self.thcountMenu, tearoff=0)
        for i in range(1, 17):
            self.menu.add_radiobutton(label=i,variable=self.thcount, command=self.Select_Thread_Num)

        self.thcountMenu["menu"] = self.menu

        self.thcountMenu.grid(column=1, row=2)

        # AWS access information entry
        self.accessid_entry = Entry(self)
        self.accessid_entry.grid(column=0, row=3)
        self.accessid_lbl = Label(text='AWS Access Key ID')
        self.accessid_lbl.grid(column=1,row=3)

        self.accessSecret_entry = Entry(self)
        self.accessSecret_entry.grid(column=0, row=4)
        self.accessSecret_lbl = Label(text='AWS Access Key Secret')
        self.accessSecret_lbl.grid(column=1,row=4)

        self.set_aws_id = Button(self, text="Set ID", fg='green', command = self.setAWSID)
        self.set_aws_id.grid(row=3, column=3)

        self.set_aws_secret = Button(self, text="Set Secret", fg='green', command = self.setAWSSECRET)
        self.set_aws_secret.grid(row=4, column=3)

        # Page number detection
        self.pages=0
        self.pageCount = Button(self, text = 'Detect Pages',
                    fg= 'green', command=self.pageCount_clicked)
        self.pageCount.grid(column=5, row=3)

        self.page_entry = Entry(self)
        self.page_entry.grid(row=1, column=5)

        self.page_entry_button = Button(self, text= 'Enter Pages',
                                        fg='green', command = self.enterPages)
        self.page_entry_button.grid(row=2, column=5)

        # Page number display
        self.TaskNumDisplay = Label(text='Detect or enter pages.\n(If setting links)')
        self.TaskNumDisplay.grid(row=0, column=5)

        # Warning
        self.warning = Label(text='Make sure all your information is correct.')
        self.warning.grid(row=5, column=5)

        # Reset Button
        self.reset_button = Button(self, text = "Reset", fg='green', command=self.ResetClicked)
        self.reset_button.grid(row=6, column=0)

        self.aws_id_label = Label(self, text = '')
        self.aws_secret_label = Label(self, text = '')
        self.unset_values = Label(self, text='')

    
    def reset_widgets(self):
    
        self.AWS_SECRET = ''
        self.AWS_ID = ''
        self.pages = 0

        self.lbl.configure(text="Update Bloodhorse Links?")
        
        self.lbl_thcount.configure(text='Thread Count: ' + str(self.thcount.get()))

        self.linkupdate.grid(column=1,row=0)

        self.btn_start.grid(column=5,row=6)
        self.thcountMenu.grid(column=1, row=1)

 
        self.accessid_entry.grid(column=0, row=3)

        self.accessid_lbl.grid(column=1,row=3)

        self.accessSecret_entry.grid(column=0, row=4)
 
        self.accessSecret_lbl.grid(column=1,row=4)

        self.set_aws_id.grid(row=3, column=3)

        self.set_aws_secret.grid(row=4, column=3)

        self.pageCount.grid(column=5, row=3)

        self.page_entry.grid(row=1, column=5)

        self.page_entry_button.grid(row=2, column=5)

        self.TaskNumDisplay.configure(text='Detect or enter pages.')

        self.warning.grid(row=5, column=5)

        self.reset_button.grid(row=6, column=0)

        self.aws_id_label.configure(text = '')
        self.aws_secret_label.configure(text = '')
        self.unset_values.configure(text='')

    # Run Program
    def start_clicked(self):
        global set_horse_links
        self.lbl.configure(text='Running')
        self.btn_start.grid_forget()
        self.linkupdate.grid_forget()
        
        self.page_entry_button.grid_forget()
        self.pageCount.grid_forget()
        self.page_entry.grid_forget()
        self.thcountMenu.grid_forget()

        self.uhorse_file.grid_forget()
        self.uhorse_lbl.grid_forget()

        self.warning.grid_forget()
        set_horse_links = self.linkupdatevar.get()

        self.setAWSID()
        self.setAWSSECRET()
        self.update()

        if self.AWS_ID == '' or self.AWS_SECRET == '' or (set_horse_links and self.pages == 0):
            self.unset_values.configure(text='Missing required values (Check page count and AWS)\nClick Reset to continue')
            self.unset_values.grid(row=8, column = 1)
        else:
            self.reset_button.grid_forget()

            logging.debug("Setting links: " + str(set_horse_links))
            logging.debug("AWS ID: " + self.AWS_ID, "AWS Secret: " + self.AWS_SECRET)
            logging.debug("Starting " + str(self.thcount.get()) + " Thread(s)")
            logging.debug("If setting links, checking " + str(self.pages) + " pages.")

            if set_horse_links:
                with sqlite3.connect("horses.db") as sqlconnection:
                    sqlcursor = sqlconnection.cursor()

                    sqlcursor.execute(""" DROP TABLE IF EXISTS HORSES; """)

                    table = """ CREATE TABLE HORSES (
                                BH_link TEXT UNIQUE NOT NULL,
                                EQ_link TEXT,
                                Name TEXT,
                                Crops TEXT,
                                Foals TEXT,
                                RA_Foals TEXT,
                                Winners TEXT,
                                Winners_B TEXT,
                                Wins TEXT,
                                Starters TEXT,
                                Starts TEXT,
                                Earnings TEXT,
                                Num_Weanlings TEXT,
                                Sales_Weanlings TEXT,
                                Num_Yearlings TEXT,
                                Sales_Yearlings TEXT
                                ); """
                    sqlcursor.execute(table)

            Start_Threads(self.thcount.get(), self.pages, self.AWS_ID, self.AWS_SECRET, Bloodhorse_Get)

            self.lbl.configure(text='Bloodhorse Links Saved.')


            with sqlite3.connect("horses.db") as sqlconnection:
                sqlcursor = sqlconnection.cursor()

                count = sqlcursor.execute(" SELECT COUNT (BH_link) FROM HORSES; ")
                countINT = count.fetchone()[0]
                logging.info(str(countINT) + " Horse links found from Bloodhorse." )
                self.TaskNumDisplay.configure(text="Getting Equineline links for:\n"+ str(countINT) +" horses.")
            

                bh_links = [bh_links[0] for bh_links in sqlcursor.execute(" SELECT BH_link FROM HORSES; ")]

                logging.debug("Bloodhorse link list value 1: " + bh_links[0])

            self.update()

            time.sleep(60)

            Start_Threads(self.thcount.get(), countINT, self.AWS_ID, self.AWS_SECRET, Bloodhorse_Find_Equineline, bh_links)

            self.lbl.configure(text="Equineline links fetched from Bloodhorse.")

            with sqlite3.connect("horses.db") as sqlconnection:
                sqlcursor = sqlconnection.cursor()

                eq_count = sqlcursor.execute(""" SELECT COUNT (EQ_link) FROM HORSES WHERE EQ_link != "ERROR" """)
                eq_countINT = eq_count.fetchone()[0]
                logging.info(str(eq_countINT) + " Equineline links found from Bloodhorse.")
                self.TaskNumDisplay.configure(text="Getting data from Equineline for:\n" + str(eq_countINT) + " horses.")

                eq_links = [eq_links[0] for eq_links in sqlcursor.execute(""" SELECT EQ_link FROM HORSES WHERE EQ_link != "ERROR" """)]

                try:
                    logging.debug("Equineline link list value 1: " + eq_links[0])
                except IndexError:
                    logging.error("No Equineline links set.")
            
            self.update()

            time.sleep(60)

            Start_Threads(self.thcount.get(), eq_countINT, self.AWS_ID, self.AWS_SECRET, Equineline_Get, eq_links)

            
            if self.unfound_horse_file.get():
                with sqlite3.connect("horses.db") as sqlconnection:
                    sqlcursor = sqlconnection.cursor()

                    horses_no_eq = [eq_links[0] for eq_links in sqlcursor.execute(""" SELECT BH_link FROM HORSES WHERE EQ_link == "ERROR" """)]

                    horses_no_data = [horse[0] for horse in sqlcursor.execute(""" SELECT EQ_link FROM HORSES WHERE EQ_link != "ERROR" AND Name IS NULL""")]

                    file_to_write = open("webscraper_horses_no_data.txt", "w")
                    file_write_string = 'Could not retrieve a link to Equineline from these Bloodhorse pages:\n'

                    for item in horses_no_eq:
                        file_write_string += item + '\n'

                    file_write_string += '\nCould not retrieve data from these Equineline pages:\n'

                    for item in horses_no_data:
                        file_write_string += item + '\n'

                    file_to_write.write(file_write_string)
                    file_to_write.close()

                    sqlcursor.execute(""" DELETE FROM HORSES WHERE EQ_link != "ERROR" AND Name IS NULL""")
                    sqlcursor.execute(""" DELETE FROM HORSES WHERE EQ_link == "ERROR" """)

                    
            conn = sqlite3.connect("horses copy.db", isolation_level=None,
                       detect_types=sqlite3.PARSE_COLNAMES)
            db_df = pandas.read_sql("SELECT * FROM HORSES", conn)
            db_df.to_csv('database.csv', index=False)

            self.lbl.configure(text=" Equineline data entered.\nComplete.")



            
                

    # Update Thread Number
    def Select_Thread_Num(self):
        self.lbl_thcount.configure(text='Thread Count: ' + str(self.thcount.get()))

    # Auto-Detect Page Number
    def pageCount_clicked(self, *args):
        try:
            bh_response = Requests.post(url=search_page_url + '1' + url_addition, headers=Header_Select(0))
            bh_text = bh_response.text
            bh_data = BeautifulSoup(bh_text, "html.parser")   
            last_page = bh_data.find("a", attrs={"class":"last"}, recursive=True)
            self.pages=int(str(last_page).split('Page=')[1].split('&')[0])
            self.TaskNumDisplay.configure(text='Pages: '+ str(self.pages))
        except IndexError:
            self.TaskNumDisplay.configure(text='Error getting page count.\nTry manually setting a number\nor trying again.')
    
    # Update Page Number Manually
    def enterPages(self):
        try:
            self.pages = int(self.page_entry.get())
            self.TaskNumDisplay.configure(text='Pages: '+ str(self.pages))
        except ValueError:
            self.TaskNumDisplay.configure(text='Error NaN')
    
    # Enter AWS information
    def setAWSID(self):
        self.AWS_ID = self.accessid_entry.get()
        self.accessid_entry.grid_forget()
        self.aws_id_label.configure(text=self.AWS_ID)
        self.aws_id_label.grid(column=0, row=3)
        self.set_aws_id.grid_forget()

    def setAWSSECRET(self):
        self.AWS_SECRET = self.accessSecret_entry.get()
        self.accessSecret_entry.grid_forget()
        self.aws_secret_label.configure(text=self.AWS_SECRET)
        self.aws_secret_label.grid(column=0, row=4)
        self.set_aws_secret.grid_forget()

    # Reset layout 
    def ResetClicked(self):
        self.aws_secret_label.grid_forget()
        self.aws_id_label.grid_forget()
        self.unset_values.grid_forget()
        
        
        self.reset_widgets()

# These can really be any numbers
max_errors = 5
request_delay = 8

# Run
if __name__ == "__main__":
    app = App()
    app.mainloop()