import os
import json
import scrapy
from scrapy.crawler import CrawlerProcess
from datetime import datetime
from urllib.parse import urlparse

# ယခုနှစ်ကို ရယူခြင်း
current_year = str(datetime.now().year)
json_filename = f"{current_year}.json"

# Repo ထဲတွင် {current_year}.json ရှိ/မရှိ စစ်ဆေးခြင်း
if os.path.exists(json_filename):
    print(f"{json_filename} ဖိုင်ရှိပြီးသားဖြစ်ပါသဖြင့် Scraping ဆက်မလုပ်ပါ။")
    exit(0)

# Scrape လုပ်ထားသော Data များသိမ်းဆည်းရန်
scraped_data = []

class ExamSpider(scrapy.Spider):
    name = 'exam_spider'
    start_urls = ['https://www.myanmarexam.org/index.html']
    
    def parse(self, response):
        self.logger.info(f"ပင်မစာမျက်နှာသို့ ရောက်ရှိပါပြီ: {response.url}")
        # ပင်မစာမျက်နှာမှ တိုင်း/ပြည်နယ် လင့်ခ်များကို ရှာဖွေခြင်း
        links = response.css('table.table tbody tr td a')
        for link in links:
            url = link.css('::attr(href)').get()
            region_name = link.css('::text').get()
            
            # စာရင်းအချက်အလက် (Stats) သို့မဟုတ် pdf လင့်ခ်များ မဟုတ်ဘဲ HTML page များကိုသာ ဆက်လက်သွားရောက်ရန်
            if url and url.endswith('.html'):
                yield response.follow(url, self.parse_region, cb_kwargs={'region_name': region_name})

    def parse_region(self, response, region_name):
        self.logger.info(f"ဒေတာများကို ရယူနေပါသည် - {region_name}: {response.url}")
        region_data = {
            "region": region_name.strip(),
            "districts": []
        }
        
        # သက်ဆိုင်ရာဒေသ စာမျက်နှာရှိ ဇယားကို ရှာဖွေခြင်း
        rows = response.css('table#tb tbody tr')
        for row in rows:
            cols = row.css('td')
            # Data မရှိလျှင် ကျော်သွားရန်
            if len(cols) >= 5:
                district = cols[1].css('::text').get(default='').strip()
                department = cols[2].css('::text').get(default='').strip()
                alphabet = cols[3].css('::text').get(default='').strip()
                file_link_tag = cols[4].css('a')
                file_url = file_link_tag.css('::attr(href)').get()
                
                if file_url:
                    # PDF ဖိုင်လမ်းကြောင်းနှင့် နာမည်ကို ခွဲထုတ်ခြင်း (ဥပမာ - ygn/YGN-009.pdf)
                    parsed_url = urlparse(file_url)
                    path_parts = parsed_url.path.strip('/').split('/')
                    
                    if len(path_parts) >= 2:
                        rel_path = f"{path_parts[-2]}/{path_parts[-1]}"
                        folder_name = path_parts[-2]
                    else:
                        rel_path = f"misc/{path_parts[-1]}"
                        folder_name = "misc"
                        
                    file_name = path_parts[-1]
                    
                    item = {
                        "name": district,
                        "department": department,
                        "alphabet": alphabet,
                        "file": rel_path
                    }
                    region_data["districts"].append(item)
                    
                    # PDF ဖိုင်များကို {current_year} အောက်တွင် Folder ခွဲ၍ သိမ်းဆည်းရန်
                    save_dir = os.path.join(current_year, folder_name)
                    os.makedirs(save_dir, exist_ok=True)
                    save_path = os.path.join(save_dir, file_name)
                    
                    # PDF ဖိုင်မရှိသေးပါက Download ဆွဲရန်
                    if not os.path.exists(save_path):
                        self.logger.info(f"PDF ဒေါင်းလုပ်ဆွဲရန် တောင်းဆိုနေပါသည် - {file_name}")
                        yield scrapy.Request(file_url, callback=self.save_pdf, cb_kwargs={'save_path': save_path})
        
        # Data များရှိမှသာ သိမ်းဆည်းရန်
        if region_data["districts"]:
            scraped_data.append(region_data)

    def save_pdf(self, response, save_path):
        self.logger.info(f"PDF ကို အောင်မြင်စွာ သိမ်းဆည်းပြီးပါပြီ - {save_path}")
        # PDF ဖိုင်ကို သိမ်းဆည်းခြင်း
        with open(save_path, 'wb') as f:
            f.write(response.body)

# Scrapy Process ကို Settings များနှင့်အတူ စတင်ခြင်း
process = CrawlerProcess(settings={
    'LOG_LEVEL': 'INFO',
    'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'CONCURRENT_REQUESTS': 5, # Server ကို ဝန်မပိစေရန် Request အရေအတွက်ကို ကန့်သတ်ထားသည်
    'DOWNLOAD_DELAY': 0.5,
    'DOWNLOAD_TIMEOUT': 20, # ၂၀ စက္ကန့်ထက်ကျော်လွန်ပါက Timeout ဖြစ်စေရန်
    'ROBOTSTXT_OBEY': False # Robots.txt စစ်ဆေးခြင်းကို ကျော်ဖြတ်ရန်
})

process.crawl(ExamSpider)
process.start()

# Scraping ပြီးဆုံးသွားချိန်တွင် Data များရှိခဲ့လျှင် JSON ဖိုင်အဖြစ် Save လုပ်ရန်
if scraped_data:
    with open(json_filename, 'w', encoding='utf-8') as f:
        json.dump(scraped_data, f, ensure_ascii=False, indent=2)
    print(f"{json_filename} ဖိုင်ကို အောင်မြင်စွာ တည်ဆောက်ပြီးပါပြီ။")
else:
    print("Website ပေါ်တွင် Data များ မတွေ့ရှိသေးပါ။")
