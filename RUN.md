# اجرای یک نوبت

پیش‌نیاز: `CARPOST_API_URL` (آدرس /exec وب‌اپ) و `CARPOST_API_TOKEN` در محیط.

## ۰. صف را بپرس (اگر خالی بود همین‌جا تمام کن)
```bash
curl -sL "$CARPOST_API_URL?api=$CARPOST_API_TOKEN&action=ping"
```
`ready` و `expired_leases` هر دو صفر → گزارش «صف خالی» و پایان؛ چیزی نصب یا دانلود نکن.

## ۱. محیط
کد در مخزن خودِ شرکت است: `github.com/fendereski/carpost`. اگر مخزن از قبل در مسیر کار باز است همان را استفاده کن؛ وگرنه:
```bash
git clone https://github.com/fendereski/carpost.git ~/carpost && cd ~/carpost
bash bootstrap.sh --models
```
(`bootstrap.sh` فونت‌ها را از npm و لوگوها را از باندل Apps Script می‌گیرد؛ هر دو فقط داده‌اند.) اگر clone ممکن نبود، باندل را از API بگیر:
```bash
mkdir -p ~/carpost && cd ~/carpost
curl -sL "$CARPOST_API_URL?api=$CARPOST_API_TOKEN&action=bundle" -o bundle.json
python3 -c "import json,base64,hashlib;d=json.load(open('bundle.json'));b=base64.b64decode(d['b64']);assert hashlib.sha256(b).hexdigest()==d['sha256'];open('bundle.zip','wb').write(b);print('bundle',d['name'],d['size'])"
unzip -oq bundle.zip && bash bootstrap.sh --models
```

## ۲. یک کار بردار
```bash
python3 job.py start
```
خروجی: کد، مسیر `jobs/<code>/`، متن مشخصات کاربر، فهرست عکس‌ها و شیت‌های مرور `photos/_grid1.jpg …` (هر شیت ۴ عکس؛ خط‌های ۱۰٪ فقط برای تخمین `keep_x`/`keep_y`). `NO_JOB` → پایان.

## ۳. کار خلاقانه (تنها جای فکر)
۱. **شیت‌های مرور را ببین** (ابزار Read روی `photos/_grid*.jpg`؛ عکس تکی را فقط وقتی جزئیات لازم است باز کن). بیرونی/داخلی را مشخص کن، بهترین سه‌رخ جلو را کاور کن، تکراری و ضعیف را حذف کن، برای هر عکس یک برچسب کوتاه فارسی بنویس. پلاک را دست نزن.
   **برچسب VIN / کارت خودرو**: هرگز در `photos` نگذار و شماره شاسی را هیچ‌جا ننویس؛ فقط اگر رویش خواناست، کشور سازنده، ماه/سال تولید، حجم موتور یا نوع سوخت را بردار و در `car.json`/کپشن استفاده کن.
۲. `jobs/<code>/car.json` بنویس (قالب پایین). فقط از متن کاربر (و اطلاعات خوانای برچسب VIN/کارت)؛ هیچ عددی حدس نزن؛ فیلد ناموجود را حذف کن. کارکرد: `mileage_km` یا `mileage_mi`. قیمت → `price`، شرایط پرداخت/تحویل → `terms`. **`fit`، `cover_fit`، `focus`، `title_bottom` ننویس.**
۳. `jobs/<code>/caption.txt` را دقیقاً با ساختار RULES.md §۵ بنویس و قبل از ذخیره یک بار بخوان: **هیچ عدد یا ویژگی‌ای دو بار نیاید**، حداکثر ۵ هشتگ فقط در خط آخر.
۴. مدل یا سال در متن نبود → `python3 job.py fail jobs/<code> "مشخصات ناقص: ..."` و برو سراغ بعدی.

قالب car.json:
```json
{
  "title": "تویوتا کرولا الیت",
  "model_en": "Toyota Corolla Elite",
  "year": "2023",
  "mileage_km": 72000,
  "color": "سفید",
  "tag": "رنگ فابریک | کم‌کارکرد",
  "options": ["ساخت تایوان", "رنگ فابریک", "فنی سالم"],
  "price": "11,000 دلار",
  "terms": "پیش‌پرداخت 4,000 دلار | مابقی 7,000 دلار هنگام ترخیص | تحویل 20 روزه",
  "cover": "jobs/<code>/photos/08.jpeg",
  "photos": [
    {"file": "jobs/<code>/photos/08.jpeg", "soften": true},
    {"file": "jobs/<code>/photos/07.jpeg", "label": "نمای سه‌رخ عقب", "soften": true},
    {"file": "jobs/<code>/photos/05.jpeg", "label": "کابین"},
    {"file": "jobs/<code>/photos/03.jpeg", "label": "داشبورد و مانیتور"},
    {"file": "jobs/<code>/photos/02.jpeg", "label": "کیلومترشمار"},
    {"file": "jobs/<code>/photos/04.jpeg", "label": "موتور"}
  ],
  "contact": true
}
```
فیلدهای اختیاری دیگر: `engine`, `hp`, `gearbox`, `fuel` (فقط اگر کاربر گفته)؛ برای عکس: `keep_x: [0.05, 0.85]` (برش دستی پانوراما)، `keep_y: [0.42, 1.0]` (برش عمودی دستی، مثلاً وقتی کیلومترشمار پایینِ یک عکس ۴:۳ افتاده و برش خودکار آن را می‌بُرد)، `blur_rects: [[x1,y1,x2,y2]]` (پیکسلی).

قالب کپشن:
```
<برند> <مدل> <سال> | <یک ویژگی> | کد XXX

<۱–۲ جمله زاویه‌ی فروش، بدون عدد>

🔹 کارکرد … کیلومتر
🔹 <موتور/گیربکس اگر داده شده>
🔹 <آپشن‌ها>
🔹 <رنگ، کشور سازنده>
🔹 قیمت … | پیش‌پرداخت … | مابقی … | تحویل …
🔹 تحویل با سند کمپانی و پلاک منطقه آزاد اینچه‌برون

💬 برای رزرو و جزئیات بیشتر، کد XXX را کامنت کنید.
📞 اطلاعات تماس در اسلاید آخر و بیو

#<برند_فارسی> #<BrandModel> #واردات_خودرو #خودرو_وارداتی #مرزخودرو
```

## ۴. بساز، ببین، تحویل بده
```bash
python3 job.py render jobs/<code>
```
`PREVIEW jobs/<code>/out/<code>_preview.jpg` را با Read ببین و چک کن: هیچ ماشینی بریده نشده؛ سوژه‌ی عکس‌های داخلی (مثلاً عدد کیلومترشمار) داخل کادر است؛ نوار مشکی فقط روی عکس‌های داخلی/موتور است. اگر چیزی غلط بود `car.json` را اصلاح کن (`keep_x`، `keep_y`، حذف عکس) و دوباره `render` بزن. بعد:
```bash
python3 job.py deliver jobs/<code>
```
آپلود و ارسال به تلگرام خودکار است؛ باید `DELIVERED` چاپ شود.

## ۵. تکرار
به گام ۲ برگرد تا `NO_JOB` (حداکثر ۵ خودرو در هر نوبت). هر خطا: `python3 job.py fail jobs/<code> "متن خطا"` و ادامه.

## گزارش پایانی
یک خط برای هر خودرو: کد، تعداد اسلاید، تحویل/خطا. هیچ توکنی در گزارش نیاید.
