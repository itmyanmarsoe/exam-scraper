import os
import json
import requests
from datetime import datetime
import scrapy
from scrapy.crawler import CrawlerProcess
from scrapy.exceptions import CloseSpider

# လက်ရှိခုနှစ်ကို ရယူခြင်း
CURRENT_YEAR = str(datetime.now().year)
JSON_FILE = f"{CURRENT_YEAR}.json"

class MyanmarExamSpider(scrapy.Spider):
    name = "myanmar_exam_spider"
    start_urls = ["http://myanmarexam.org"]
    
    custom_settings = {
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'LOG_LEVEL': 'INFO',
        'CONCURRENT_REQUESTS': 8  # ဝဘ်ဆိုက်မကျစေရန် ညင်သာစွာ ဆွဲခြင်း
    }

    def __init__(self, *args, **kwargs):
        super(MyanmarExamSpider, self).__init__(*args, **kwargs)
        self.final_data = {}  # Region အလိုက် Data များကို ခေတ္တသိမ်းရန် Dict

    def parse(self, response):
        # ⚠️ ပင်မစာမျက်နှာရှိ Table တွင် <a> tag များ မရှိပါက Data မရှိဟု သတ်မှတ်ကာ ရပ်တန့်မည်
        region_links = response.css('table.table tbody tr td a')
        if not region_links:
            self.logger.error("ပင်မစာမျက်နှာတွင် တိုင်းဒေသကြီးနှင့် ပြည်နယ်လင့်ခ်များ မတွေ့ရှိရပါ။")
            raise CloseSpider("HTML Structure Changed")

        for link in region_links:
            region_name = link.css('::text').get(default="").strip()
            href = link.css('::attr(href)').get()
            
            # နိုင်ငံခြား သို့မဟုတ် statistics PDF ဖိုင် တိုက်ရိုက်ဖြစ်နေပါက သီးသန့်ကိုင်တွယ်ခြင်း
            if href.endswith('.pdf'):
                self.process_direct_pdf(region_name, response.urljoin(href))
                continue
                
            if href:
                absolute_url = response.urljoin(href)
                # ဒေသအလိုက် Page များကို ထပ်ဆင့် Scrape လုပ်ရန် လှမ်းခေါ်ခြင်း
                yield scrapy.Request(
                    url=absolute_url, 
                    callback=self.parse_region, 
                    meta={'region_name': region_name}
                )

    def parse_region(self, response):
        region_name = response.meta['region_name']
        
        # ⚠️ သတ်မှတ်ထားသော #tb ဇယား မရှိလျှင် Scrape ဆက်မလုပ်ဘဲ ရပ်တန့်မည်
        table_rows = response.css('table#tb tbody tr')
        if not table_rows:
            self.logger.error(f"[{region_name}] စာမျက်နှာတွင် အောင်စာရင်းဇယား (table#tb) ကို မတွေ့ရှိရပါ။")
            raise CloseSpider("Region Table Missing")

        districts_list = []
        
        for row in table_rows:
            cells = row.css('td')
            if len(cells) < 5:
                continue

            # HTML ပုံစံအတိုင်း Column များကို ဆွဲထုတ်ခြင်း
            dist_name = cells[1].css('::text').get(default="").strip()
            department = cells[2].css('::text').get(default="").strip()
            alphabet = cells[3].css('::text').get(default="").strip()
            pdf_url = cells[4].css('a::attr(href)').get(default="")

            if pdf_url and pdf_url.endswith('.pdf'):
                abs_pdf_url = response.urljoin(pdf_url)
                
                # AWS S3 သို့မဟုတ် Relative link များထဲမှ ဖိုင်လမ်းကြောင်း သတ်မှတ်ခြင်း (e.g., sgg/SGG-001.pdf)
                url_parts = pdf_url.split('/')
                if len(url_parts) >= 2:
                    relative_path = f"{url_parts[-2]}/{url_parts[-1]}"
                else:
                    relative_path = f"unknown/{url_parts[-1]}"

                # PDF အား ဒေါင်းလုဒ်ဆွဲရန် လုပ်ဆောင်ခြင်း
                self.download_pdf(abs_pdf_url, relative_path)

                districts_list.append({
                    "name": dist_name,
                    "department": department,
                    "alphabet": alphabet,
                    "file": relative_path
                })

        if districts_list:
            if region_name not in self.final_data:
                self.final_data[region_name] = []
            self.final_data[region_name].extend(districts_list)

    def process_direct_pdf(self, region_name, pdf_url):
        """ တိုက်ရိုက် PDF လင့်ခ်များအတွက် (ဥပမာ - နိုင်ငံခြား) """
        filename = pdf_url.split('/')[-1]
        relative_path = f"fgn/{filename}" if "FGN" in filename else f"stats/{filename}"
        
        self.download_pdf(pdf_url, relative_path)
        
        if region_name not in self.final_data:
            self.final_data[region_name] = []
        self.final_data[region_name].append({
            "name": region_name,
            "department": region_name,
            "alphabet": "-",
            "file": relative_path
        })

    def download_pdf(self, url, relative_path):
        """ PDF များကို {current_year} prefix အောက်တွင် သိမ်းဆည်းပေးမည့် လုပ်ဆောင်ချက် """
        target_path = os.path.join(CURRENT_YEAR, relative_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        
        if os.path.exists(target_path):
            return  # ရှိပြီးသားဆိုလျှင် ထပ်မဒေါင်းတော့ပါ
            
        try:
            self.logger.info(f"Downloading: {target_path}")
            res = requests.get(url, timeout=30)
            if res.status_code == 200:
                with open(target_path, "wb") as f:
                    f.write(res.content)
        except Exception as e:
            self.logger.error(f"Error downloading PDF {url}: {str(e)}")

    def closed(self, reason):
        """ Spider ပိတ်သွားချိန်တွင် သတ်မှတ်ထားသော Format အတိုင်း JSON ထုတ်ပေးခြင်း """
        if reason == "finished" and self.final_data:
            formatted_json = []
            for region, districts in self.final_data.items():
                formatted_json.append({
                    "region": region,
                    "districts": districts
                })
            
            with open(JSON_FILE, "w", encoding="utf-8") as f:
                json.dump(formatted_json, f, ensure_ascii=False, indent=2)
            self.logger.info(f"အောင်မြင်စွာဖြင့် {JSON_FILE} ကို ဖန်တီးပြီးပါပြီ။")

def main():
    if os.path.exists(JSON_FILE):
        print(f"[{JSON_FILE}] ရှိပြီးသား ဖြစ်သောကြောင့် Scrape ထပ်မလုပ်ပါ။")
        return

    process = CrawlerProcess()
    process.crawl(MyanmarExamSpider)
    process.start()

if __name__ == "__main__":
    main()
