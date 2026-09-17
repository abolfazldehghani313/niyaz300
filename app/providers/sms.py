import requests

class SMSProvider:
    name="base"
    def __init__(self,cfg): self.cfg=cfg or {}
    def send(self,to,message): raise NotImplementedError
    def test_connection(self): return {"ok":False,"error":"تست اتصال برای این سرویس پیاده‌سازی نشده است."}

class ConsoleSMS(SMSProvider):
    name="console"
    def send(self,to,message):
        print(f"[Niyaz SMS DEV] {to}: {message}")
        return {"ok":True}
    def test_connection(self): return {"ok":True,"message":"حالت تست داخلی فعال است."}

class SMSIR(SMSProvider):
    name="smsir"
    BASE="https://api.sms.ir/v1/"
    def _headers(self):
        key=(self.cfg.get("api_key") or "").strip()
        return {"Content-Type":"application/json","Accept":"application/json","x-api-key":key}
    def _base(self): return (self.cfg.get("endpoint") or self.BASE).rstrip("/")+"/"
    def send(self,to,message):
        key=(self.cfg.get("api_key") or "").strip(); line=str(self.cfg.get("sender") or "").strip()
        if not key: return {"ok":False,"error":"API Key سرویس SMS.ir وارد نشده است."}
        if not line: return {"ok":False,"error":"شماره خط SMS.ir وارد نشده است."}
        try:
            line_num=int(line)
            payload={"lineNumber":line_num,"messageText":message,"mobiles":[str(to)]}
            r=requests.post(self._base()+"send/bulk",json=payload,headers=self._headers(),timeout=15)
            if 200<=r.status_code<300:
                data=r.json() if r.text else {}
                return {"ok":True,"data":data}
            return {"ok":False,"error":f"SMS.ir: HTTP {r.status_code} - {r.text[:300]}"}
        except Exception as e: return {"ok":False,"error":f"خطا در ارسال SMS.ir: {e}"}
    def send_otp(self,to,code):
        key=(self.cfg.get("api_key") or "").strip()
        template_id=str(self.cfg.get("template_id") or "").strip()
        if not key: return {"ok":False,"error":"API Key وارد نشده است."}
        if not template_id: return {"ok":False,"error":"Template ID احراز هویت وارد نشده است."}
        try:
            payload={"mobile":str(to),"templateId":int(template_id),"parameters":[{"name":"CODE","value":str(code)}]}
            r=requests.post(self._base()+"send/verify",json=payload,headers=self._headers(),timeout=15)
            data=r.json() if r.text else {}
            return {"ok":200<=r.status_code<300,"data":data,"error":None if 200<=r.status_code<300 else r.text[:300]}
        except Exception as e: return {"ok":False,"error":f"خطا در OTP SMS.ir: {e}"}

    def verify(self,to,template_id,code):
        return self.send_otp(to,code)
    def test_connection(self):
        key=(self.cfg.get("api_key") or "").strip()
        if not key: return {"ok":False,"error":"API Key SMS.ir وارد نشده است."}
        try:
            r=requests.get(self._base()+"credit",headers=self._headers(),timeout=15)
            if 200<=r.status_code<300:
                data=r.json() if r.text else {}
                return {"ok":True,"message":"اتصال SMS.ir موفق است.","data":data}
            return {"ok":False,"error":f"SMS.ir: HTTP {r.status_code} - {r.text[:300]}"}
        except Exception as e: return {"ok":False,"error":f"خطا در اتصال SMS.ir: {e}"}

class GenericSMS(SMSProvider):
    def send(self,to,message): return {"ok":False,"error":"Adapter این سرویس در این نسخه پیاده‌سازی نشده است."}

class Kavenegar(GenericSMS): name="kavenegar"
class Melipayamak(GenericSMS): name="melipayamak"
class FarazSMS(GenericSMS): name="farazsms"
class IPPanel(GenericSMS): name="ippanel"
class CustomSMS(GenericSMS): name="custom"

def get_sms_provider(name,cfg):
    m={"console":ConsoleSMS,"smsir":SMSIR,"kavenegar":Kavenegar,"melipayamak":Melipayamak,
       "farazsms":FarazSMS,"ippanel":IPPanel,"custom":CustomSMS}
    return m.get(name,CustomSMS)(cfg)
