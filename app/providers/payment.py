import uuid, requests

class PaymentProvider:
    name = "base"
    def __init__(self, cfg): self.cfg = cfg or {}
    def request(self, amount, callback_url, description): raise NotImplementedError
    def verify(self, amount, authority): raise NotImplementedError
    def test_connection(self): return {"ok": False, "error": "تست اتصال برای این درگاه پیاده‌سازی نشده است."}

class MockPayment(PaymentProvider):
    name="mock"
    def request(self,amount,callback_url,description):
        authority="MOCK-"+uuid.uuid4().hex
        sep="&" if "?" in callback_url else "?"
        order_id=str(self.cfg.get("order_id") or "")
        return {"ok":True,"authority":authority,"payment_url":f"{callback_url}{sep}mock=1&authority={authority}&order_id={order_id}"}
    def verify(self,amount,authority): return {"ok":True,"reference":"MOCK-"+authority[-10:]}
    def test_connection(self): return {"ok":True,"message":"درگاه تست داخلی آماده است."}

class Zarinpal(PaymentProvider):
    name="zarinpal"
    REQUEST="https://payment.zarinpal.com/pg/v4/payment/request.json"
    VERIFY="https://payment.zarinpal.com/pg/v4/payment/verify.json"
    START="https://www.zarinpal.com/pg/StartPay/{authority}"
    def _amount(self, amount):
        unit=(self.cfg.get("unit") or "toman").lower()
        return int(amount)*10 if unit in ("toman","تومان") else int(amount)
    def request(self,amount,callback_url,description):
        merchant=(self.cfg.get("merchant_id") or self.cfg.get("api_key") or "").strip()
        if not merchant: return {"ok":False,"error":"Merchant ID درگاه وارد نشده است."}
        payload={"merchant_id":merchant,"amount":self._amount(amount),"description":description,"callback_url":callback_url}
        try:
            r=requests.post(self.REQUEST,json=payload,timeout=15); data=r.json()
            if r.ok and data.get("data",{}).get("code")==100:
                authority=data["data"]["authority"]
                return {"ok":True,"authority":authority,"payment_url":self.START.format(authority=authority)}
            return {"ok":False,"error":f"خطای زرین‌پال: {data.get('errors') or data.get('data') or r.text[:300]}"}
        except Exception as e: return {"ok":False,"error":f"خطا در اتصال به زرین‌پال: {e}"}
    def verify(self,amount,authority):
        merchant=(self.cfg.get("merchant_id") or self.cfg.get("api_key") or "").strip()
        payload={"merchant_id":merchant,"amount":self._amount(amount),"authority":authority}
        try:
            r=requests.post(self.VERIFY,json=payload,timeout=15); data=r.json(); code=data.get("data",{}).get("code")
            if r.ok and code in (100,101): return {"ok":True,"reference":str(data["data"].get("ref_id",authority))}
            return {"ok":False,"error":f"تأیید پرداخت ناموفق بود: {data.get('errors') or data.get('data') or r.text[:300]}"}
        except Exception as e: return {"ok":False,"error":f"خطا در Verify زرین‌پال: {e}"}
    def test_connection(self):
        merchant=(self.cfg.get("merchant_id") or self.cfg.get("api_key") or "").strip()
        if not merchant: return {"ok":False,"error":"Merchant ID وارد نشده است."}
        try:
            r=requests.get("https://payment.zarinpal.com",timeout=10)
            if r.status_code < 500: return {"ok":True,"message":"ارتباط با سرویس زرین‌پال برقرار است. برای تست کامل تراکنش، یک پرداخت آزمایشی انجام دهید."}
            return {"ok":False,"error":"سرویس زرین‌پال در دسترس نیست."}
        except Exception as e: return {"ok":False,"error":f"سرویس زرین‌پال در دسترس نیست: {e}"}

class Zibal(PaymentProvider):
    name="zibal"
    REQUEST="https://gateway.zibal.ir/v1/request"
    VERIFY="https://gateway.zibal.ir/v1/verify"
    START="https://gateway.zibal.ir/start/{track_id}"
    def _amount(self, amount):
        return int(amount)*10 if (self.cfg.get("unit") or "toman").lower() in ("toman","تومان") else int(amount)
    def request(self,amount,callback_url,description):
        merchant=(self.cfg.get("merchant_id") or self.cfg.get("api_key") or "").strip()
        if not merchant: return {"ok":False,"error":"Merchant ID زیبال وارد نشده است."}
        try:
            r=requests.post(self.REQUEST,json={"merchant":merchant,"amount":self._amount(amount),"callbackUrl":callback_url,"description":description},timeout=15)
            d=r.json();
            if r.ok and d.get("result")==100:
                tid=str(d.get("trackId")); return {"ok":True,"authority":tid,"payment_url":self.START.format(track_id=tid)}
            return {"ok":False,"error":f"خطای زیبال: {d.get('message') or d.get('result') or r.text[:300]}"}
        except Exception as e: return {"ok":False,"error":f"خطا در اتصال به زیبال: {e}"}
    def verify(self,amount,authority,callback=None):
        merchant=(self.cfg.get("merchant_id") or self.cfg.get("api_key") or "").strip()
        try:
            r=requests.post(self.VERIFY,json={"merchant":merchant,"trackId":int(authority)},timeout=15); d=r.json()
            if r.ok and d.get("result") in (100,201): return {"ok":True,"reference":str(d.get("refNumber") or d.get("trackId") or authority),"data":d}
            return {"ok":False,"error":f"تأیید زیبال ناموفق بود: {d.get('message') or d.get('result') or r.text[:300]}"}
        except Exception as e: return {"ok":False,"error":f"خطا در Verify زیبال: {e}"}
    def test_connection(self):
        return {"ok":bool((self.cfg.get("merchant_id") or self.cfg.get("api_key") or "").strip()),"message":"تنظیمات Merchant زیبال ثبت شده است. تست کامل با تراکنش واقعی انجام می‌شود." if (self.cfg.get("merchant_id") or self.cfg.get("api_key")) else "Merchant ID زیبال وارد نشده است."}

class IDPay(PaymentProvider):
    name="idpay"
    BASE="https://api.idpay.ir/v1.1/payment"
    def _headers(self):
        h={"Content-Type":"application/json","X-API-KEY":(self.cfg.get("api_key") or "").strip()}
        if (self.cfg.get("mode") or "test").lower()=="test": h["X-SANDBOX-API-KEY"]=h["X-API-KEY"]
        return h
    def _amount(self,amount):
        return int(amount)*10 if (self.cfg.get("unit") or "toman").lower() in ("toman","تومان") else int(amount)
    def request(self,amount,callback_url,description):
        key=(self.cfg.get("api_key") or "").strip()
        if not key: return {"ok":False,"error":"API Key آی‌دی‌پی وارد نشده است."}
        order_id=str(self.cfg.get("order_id") or uuid.uuid4().hex[:24])
        payload={"order_id":order_id,"amount":self._amount(amount),"callback":callback_url,"desc":description}
        try:
            r=requests.post(self.BASE,json=payload,headers=self._headers(),timeout=15); d=r.json()
            if r.ok and d.get("id") and d.get("link"):
                return {"ok":True,"authority":str(d["id"]),"payment_url":d["link"],"order_id":order_id}
            return {"ok":False,"error":f"خطای IDPay: {d.get('error_message') or d.get('error_code') or r.text[:300]}"}
        except Exception as e: return {"ok":False,"error":f"خطا در اتصال به IDPay: {e}"}
    def verify(self,amount,authority,callback=None):
        order_id=(callback or {}).get("order_id") or (callback or {}).get("orderId") or self.cfg.get("order_id") or ""
        if not order_id: return {"ok":False,"error":"order_id برای Verify آی‌دی‌پی دریافت نشد."}
        try:
            r=requests.post(self.BASE+"/verify",json={"id":authority,"order_id":order_id},headers=self._headers(),timeout=15); d=r.json()
            if r.ok and d.get("status") in (100,101): return {"ok":True,"reference":str(d.get("track_id") or authority),"data":d}
            return {"ok":False,"error":f"تأیید IDPay ناموفق بود: {d.get('error_message') or d.get('status') or r.text[:300]}"}
        except Exception as e: return {"ok":False,"error":f"خطا در Verify IDPay: {e}"}
    def test_connection(self):
        return {"ok":bool((self.cfg.get("api_key") or "").strip()),"message":"API Key آی‌دی‌پی ثبت شده است. تست کامل با تراکنش انجام می‌شود." if self.cfg.get("api_key") else "API Key آی‌دی‌پی وارد نشده است."}

class NextPay(PaymentProvider):
    name="nextpay"
    TOKEN="https://nextpay.org/nx/gateway/token"
    VERIFY="https://nextpay.org/nx/gateway/verify"
    START="https://nextpay.org/nx/gateway/payment/{trans_id}"
    def _amount(self,amount):
        return int(amount)*10 if (self.cfg.get("unit") or "toman").lower() in ("toman","تومان") else int(amount)
    def request(self,amount,callback_url,description):
        key=(self.cfg.get("api_key") or self.cfg.get("merchant_id") or "").strip()
        if not key: return {"ok":False,"error":"API Key نکست‌پی وارد نشده است."}
        order_id=str(self.cfg.get("order_id") or uuid.uuid4().hex[:24])
        payload={"api_key":key,"order_id":order_id,"amount":self._amount(amount),"callback_uri":callback_url,"currency":"IRR"}
        try:
            r=requests.post(self.TOKEN,data=payload,timeout=15); d=r.json(); code=d.get("code")
            trans=d.get("trans_id") or d.get("transId")
            if trans and str(code) in ("-1","200","1") or trans:
                return {"ok":True,"authority":str(trans),"payment_url":self.START.format(trans_id=trans),"order_id":order_id}
            return {"ok":False,"error":f"خطای نکست‌پی: {d.get('message') or d.get('code') or r.text[:300]}"}
        except Exception as e: return {"ok":False,"error":f"خطا در اتصال به نکست‌پی: {e}"}
    def verify(self,amount,authority,callback=None):
        key=(self.cfg.get("api_key") or self.cfg.get("merchant_id") or "").strip()
        try:
            r=requests.post(self.VERIFY,data={"api_key":key,"trans_id":authority,"amount":self._amount(amount)},timeout=15); d=r.json(); code=d.get("code")
            if str(code) in ("0","200") or (code is None and d.get("trans_id")):
                return {"ok":True,"reference":str(d.get("trans_id") or authority),"data":d}
            return {"ok":False,"error":f"تأیید نکست‌پی ناموفق بود: {d.get('message') or code or r.text[:300]}"}
        except Exception as e: return {"ok":False,"error":f"خطا در Verify نکست‌پی: {e}"}
    def test_connection(self):
        return {"ok":bool((self.cfg.get("api_key") or self.cfg.get("merchant_id") or "").strip()),"message":"کلید نکست‌پی ثبت شده است. تست کامل با تراکنش انجام می‌شود." if (self.cfg.get("api_key") or self.cfg.get("merchant_id")) else "API Key نکست‌پی وارد نشده است."}

class Aqayepardakht(PaymentProvider):
    name="aqayepardakht"
    # آقای پرداخت uses a PIN/trace based flow. Endpoint can be overridden from admin.
    def _base(self): return (self.cfg.get("endpoint") or "https://panel.aqayepardakht.ir/api/v1").rstrip("/")
    def _amount(self,amount): return int(amount)*10 if (self.cfg.get("unit") or "toman").lower() in ("toman","تومان") else int(amount)
    def request(self,amount,callback_url,description):
        pin=(self.cfg.get("api_key") or self.cfg.get("merchant_id") or "").strip()
        if not pin: return {"ok":False,"error":"PIN آقای پرداخت وارد نشده است."}
        # Provider installations differ; endpoint is configurable so the merchant can use the exact endpoint supplied by Aqaye Pardakht.
        return {"ok":False,"error":"برای آقای پرداخت، PIN و Endpoint رسمی حساب پذیرنده را در تنظیمات وارد کنید؛ این نسخه از اجرای endpoint حدسی خودداری می‌کند."}
    def verify(self,amount,authority,callback=None): return {"ok":False,"error":"Verify آقای پرداخت تا زمان تعیین Endpoint رسمی حساب پذیرنده انجام نمی‌شود."}
    def test_connection(self): return {"ok":bool((self.cfg.get("api_key") or self.cfg.get("merchant_id") or "").strip()),"message":"PIN آقای پرداخت ثبت شده است؛ تست تراکنش پس از تعیین Endpoint رسمی انجام می‌شود." if (self.cfg.get("api_key") or self.cfg.get("merchant_id")) else "PIN آقای پرداخت وارد نشده است."}

class ConfigurableProvider(PaymentProvider):
    def request(self,amount,callback_url,description): return {"ok":False,"error":"این درگاه قرارداد API عمومی متصل در پروژه ندارد."}
    def verify(self,amount,authority,callback=None): return {"ok":False,"error":"Verify این درگاه پیاده‌سازی نشده است."}

class DirectBank(ConfigurableProvider): name="bank"
class CustomPayment(ConfigurableProvider): name="custom"

def get_payment_provider(name,cfg):
    m={"mock":MockPayment,"zarinpal":Zarinpal,"zibal":Zibal,"idpay":IDPay,"nextpay":NextPay,
       "aqayepardakht":Aqayepardakht,"bank":DirectBank,"custom":CustomPayment}
    return m.get(name,CustomPayment)(cfg)
