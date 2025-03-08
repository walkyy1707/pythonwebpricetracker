import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import time
import requests
from bs4 import BeautifulSoup
import sqlite3
from datetime import datetime
import re

# Predefined selectors for popular websites
PREDEFINED_SELECTORS = {
    "Amazon": {
        "price": "span.a-price-whole",
        "availability": "#availability > span"
    },
    "eBay": {
        "price": "span#prcIsum",
        "availability": "span#qtySubTxt"
    },
    "Custom": {
        "price": "",
        "availability": ""
    }
}

# Database Functions
def init_db():
    conn = sqlite3.connect('price_tracking.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS products
                 (id INTEGER PRIMARY KEY, url TEXT, price_selector TEXT, availability_selector TEXT, alert_threshold REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS price_history
                 (id INTEGER PRIMARY KEY, product_id INTEGER, price REAL, availability TEXT, timestamp DATETIME)''')
    conn.commit()
    conn.close()

def add_product(url, price_selector, availability_selector, alert_threshold):
    conn = sqlite3.connect('price_tracking.db')
    c = conn.cursor()
    c.execute("INSERT INTO products (url, price_selector, availability_selector, alert_threshold) VALUES (?, ?, ?, ?)",
              (url, price_selector, availability_selector, alert_threshold))
    product_id = c.lastrowid
    conn.commit()
    conn.close()
    return product_id

def get_products():
    conn = sqlite3.connect('price_tracking.db')
    c = conn.cursor()
    c.execute("SELECT id, url, price_selector, availability_selector, alert_threshold FROM products")
    products = c.fetchall()
    conn.close()
    return products

def add_price_history(product_id, price, availability):
    conn = sqlite3.connect('price_tracking.db')
    c = conn.cursor()
    c.execute("INSERT INTO price_history (product_id, price, availability, timestamp) VALUES (?, ?, ?, ?)",
              (product_id, price, availability, datetime.now()))
    conn.commit()
    conn.close()

def get_latest_data(product_id):
    conn = sqlite3.connect('price_tracking.db')
    c = conn.cursor()
    c.execute("SELECT price, availability, timestamp FROM price_history WHERE product_id = ? ORDER BY timestamp DESC LIMIT 1",
              (product_id,))
    data = c.fetchone()
    conn.close()
    return data

def get_price_history(product_id):
    conn = sqlite3.connect('price_tracking.db')
    c = conn.cursor()
    c.execute("SELECT timestamp, price, availability FROM price_history WHERE product_id = ? ORDER BY timestamp DESC LIMIT 100",
              (product_id,))
    history = c.fetchall()
    conn.close()
    return history

# Scraper Functions
def fetch_page_with_retry(url, max_retries=3):
    for attempt in range(max_retries):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except requests.RequestException as e:
            print(f"Attempt {attempt + 1} failed for {url}: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
    print(f"All attempts failed for {url}")
    return None

def extract_data(soup, price_selector, availability_selector):
    price = None
    availability = None
    try:
        price_element = soup.select_one(price_selector)
        if price_element:
            price_text = re.sub(r'[^\d.]', '', price_element.get_text())
            price = float(price_text) if price_text else None
    except Exception as e:
        print(f"Error extracting price: {e}")
    try:
        availability_element = soup.select_one(availability_selector)
        if availability_element:
            availability = availability_element.get_text().strip()
    except Exception as e:
        print(f"Error extracting availability: {e}")
    return price, availability

def scrape_products(update_queue):
    products = get_products()
    for product in products:
        product_id, url, price_selector, availability_selector, alert_threshold = product
        soup = fetch_page_with_retry(url)
        if soup:
            price, availability = extract_data(soup, price_selector, availability_selector)
            add_price_history(product_id, price, availability)
            if price is not None and alert_threshold is not None and price < alert_threshold:
                update_queue.put({"type": "alert", "text": f"Price dropped below {alert_threshold} for {url}"})

# GUI Application
class PriceTrackerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Price Tracker")
        init_db()
        self.update_queue = queue.Queue()
        self.tracking_running = False
        self.tracking_thread = None
        self.website_var = tk.StringVar()
        self.create_widgets()
        self.refresh_display()
        self.check_queue()

    def create_widgets(self):
        # Input Frame
        input_frame = tk.Frame(self.root)
        input_frame.pack(pady=10)

        tk.Label(input_frame, text="Website:").grid(row=0, column=0)
        self.website_combobox = ttk.Combobox(input_frame, textvariable=self.website_var, values=list(PREDEFINED_SELECTORS.keys()))
        self.website_combobox.grid(row=0, column=1)
        self.website_combobox.bind("<<ComboboxSelected>>", self.update_selectors)

        tk.Label(input_frame, text="URL:").grid(row=1, column=0)
        self.url_entry = tk.Entry(input_frame, width=50)
        self.url_entry.grid(row=1, column=1)

        tk.Label(input_frame, text="Price Selector:").grid(row=2, column=0)
        self.price_selector_entry = tk.Entry(input_frame, width=50)
        self.price_selector_entry.grid(row=2, column=1)

        tk.Label(input_frame, text="Availability Selector:").grid(row=3, column=0)
        self.availability_selector_entry = tk.Entry(input_frame, width=50)
        self.availability_selector_entry.grid(row=3, column=1)

        tk.Label(input_frame, text="Alert Threshold:").grid(row=4, column=0)
        self.alert_threshold_entry = tk.Entry(input_frame, width=50)
        self.alert_threshold_entry.grid(row=4, column=1)

        tk.Button(input_frame, text="Add Product", command=self.add_product).grid(row=5, column=0, columnspan=2)

        # Display Table
        self.tree = ttk.Treeview(self.root, columns=('ID', 'URL', 'Price', 'Availability', 'Last Updated', 'Action'), show='headings')
        self.tree.heading('ID', text='ID')
        self.tree.column('ID', width=0, stretch=tk.NO)  # Hide ID column
        self.tree.heading('URL', text='URL')
        self.tree.heading('Price', text='Price')
        self.tree.heading('Availability', text='Availability')
        self.tree.heading('Last Updated', text='Last Updated')
        self.tree.heading('Action', text='Action')
        self.tree.pack(pady=10)
        self.tree.bind("<Double-1>", self.on_double_click)

        # Control Frame
        control_frame = tk.Frame(self.root)
        control_frame.pack(pady=10)

        tk.Label(control_frame, text="Interval (minutes):").grid(row=0, column=0)
        self.interval_entry = tk.Entry(control_frame, width=10)
        self.interval_entry.grid(row=0, column=1)
        self.interval_entry.insert(0, "60")

        self.start_button = tk.Button(control_frame, text="Start Tracking", command=self.start_tracking)
        self.start_button.grid(row=0, column=2)

        self.stop_button = tk.Button(control_frame, text="Stop Tracking", command=self.stop_tracking, state=tk.DISABLED)
        self.stop_button.grid(row=0, column=3)

        tk.Button(control_frame, text="Scrape Now", command=self.scrape_now).grid(row=0, column=4)

    def update_selectors(self, event):
        website = self.website_var.get()
        if website in PREDEFINED_SELECTORS:
            self.price_selector_entry.delete(0, tk.END)
            self.price_selector_entry.insert(0, PREDEFINED_SELECTORS[website]["price"])
            self.availability_selector_entry.delete(0, tk.END)
            self.availability_selector_entry.insert(0, PREDEFINED_SELECTORS[website]["availability"])

    def add_product(self):
        website = self.website_var.get()
        url = self.url_entry.get()
        price_selector = self.price_selector_entry.get()
        availability_selector = self.availability_selector_entry.get()
        alert_threshold = self.alert_threshold_entry.get()
        if url and price_selector:
            try:
                alert_threshold = float(alert_threshold) if alert_threshold else None
            except ValueError:
                messagebox.showerror("Error", "Alert Threshold must be a number.")
                return
            product_id = add_product(url, price_selector, availability_selector, alert_threshold)
            self.refresh_display()
            self.url_entry.delete(0, tk.END)
            self.price_selector_entry.delete(0, tk.END)
            self.availability_selector_entry.delete(0, tk.END)
            self.alert_threshold_entry.delete(0, tk.END)

    def refresh_display(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        products = get_products()
        for product in products:
            product_id, url, _, _, _ = product
            data = get_latest_data(product_id)
            if data:
                price, availability, timestamp = data
                price_str = f"${price:.2f}" if price is not None else "N/A"
                availability_str = availability if availability is not None else "N/A"
                self.tree.insert('', 'end', values=(product_id, url, price_str, availability_str, timestamp, "View History"))
            else:
                self.tree.insert('', 'end', values=(product_id, url, "N/A", "N/A", "Never", "View History"))

    def start_tracking(self):
        if not self.tracking_running:
            self.tracking_running = True
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            interval = int(self.interval_entry.get()) * 60
            self.tracking_thread = threading.Thread(target=self.tracking_loop, args=(interval, self.update_queue))
            self.tracking_thread.start()

    def stop_tracking(self):
        self.tracking_running = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def tracking_loop(self, interval, update_queue):
        while self.tracking_running:
            scrape_products(update_queue)
            update_queue.put("update")
            time.sleep(interval)

    def scrape_now(self):
        if not self.tracking_running:
            scrape_products(self.update_queue)
            self.update_queue.put("update")
        else:
            messagebox.showwarning("Warning", "Tracking is already running.")

    def on_double_click(self, event):
        item = self.tree.identify('item', event.x, event.y)
        column = self.tree.identify('column', event.x, event.y)
        if column == 'Action':
            product_id = self.tree.item(item)['values'][0]  # Get the hidden product_id
            self.show_history(product_id)

    def show_history(self, product_id):
        history_window = tk.Toplevel(self.root)
        history_window.title("Price History")
        tree = ttk.Treeview(history_window, columns=('Timestamp', 'Price', 'Availability'), show='headings')
        tree.heading('Timestamp', text='Timestamp')
        tree.heading('Price', text='Price')
        tree.heading('Availability', text='Availability')
        tree.pack(pady=10)

        history = get_price_history(product_id)
        for row in history:
            timestamp, price, availability = row
            price_str = f"${price:.2f}" if price is not None else "N/A"
            availability_str = availability if availability is not None else "N/A"
            tree.insert('', 'end', values=(timestamp, price_str, availability_str))

    def check_queue(self):
        try:
            while True:
                message = self.update_queue.get_nowait()
                if message == "update":
                    self.refresh_display()
                elif isinstance(message, dict) and message.get("type") == "alert":
                    messagebox.showinfo("Price Alert", message["text"])
        except queue.Empty:
            pass
        self.root.after(100, self.check_queue)

# Run the App
if __name__ == "__main__":
    root = tk.Tk()
    app = PriceTrackerApp(root)
    root.mainloop()