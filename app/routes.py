import os, re, json, secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from . import db
from .models import *
from .license import required as license_required, status as license_status, activate as license_activate, clear as license_clear

main=Blueprint("main",__name__)
ADMIN_PHONE=os.getenv("ADMIN_PHONE","09055018315").strip()
ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD","123456789")
PREVIEW_MODE=os.getenv("PREVIEW_MODE","1").strip().lower() in {"1","true","yes","on"}


def preview_enabled():
    return PREVIEW_MODE


def ensure_preview_user():
    """Create/select the demo administrator used by the public preview build."""
    if not preview_enabled():
        return None
    username="__preview_admin__"
    u=User.query.filter_by(username=username).first()
    if not u:
        u=User(username=username,password_hash=generate_password_hash(secrets.token_urlsafe(24)),phone="",full_name="مدیر نسخه نمایشی",is_admin=True,role="admin",is_active=True)
        db.session.add(u); db.session.commit()
    elif not u.is_admin or not u.is_active:
        u.is_admin=True; u.role="admin"; u.is_active=True; db.session.commit()
    session["user_id"]=u.id
    session["preview_mode"]=True
    return u


def csrf():
    if "_csrf" not in session: session["_csrf"]=secrets.token_urlsafe(32)
    return session["_csrf"]

@main.app_context_processor
def template_globals(): return {"csrf_token":csrf}

@main.before_request
def protect():
    if request.method=="POST" and request.form.get("_csrf")!=session.get("_csrf"): abort(400,"CSRF token invalid")
    # Public preview mode intentionally bypasses authentication and license gating so
    # marketplace visitors can inspect the full storefront and admin UI.
    if preview_enabled():
        ensure_preview_user()
        return None
    # License gate: keep authentication and activation pages reachable when a license
    # expires so the administrator can renew it. Enable with LICENSE_REQUIRED=1.
    if license_required():
        endpoint = request.endpoint or ""
        allowed = endpoint in {"main.auth", "main.logout", "main.license"} or request.path.startswith("/static/")
        if not allowed:
            st = license_status()
            if not st.get("valid"):
                return redirect(url_for("main.license", expired=1))
def login_required(f):
    @wraps(f)
    def w(*a,**k):
        if preview_enabled():
            ensure_preview_user()
            return f(*a,**k)
        if not session.get("user_id"): return redirect(url_for("main.auth",next=request.path))
        return f(*a,**k)
    return w


def admin_required(f):
    @wraps(f)
    def w(*a,**k):
        if preview_enabled():
            u=ensure_preview_user()
            if u: return f(*a,**k)
        u=db.session.get(User,session.get("user_id"))
        if not u or not u.is_admin: abort(403)
        return f(*a,**k)
    return w


def setting(key,default=""):
    x=db.session.execute(db.select(SiteSetting).filter_by(key=key)).scalar_one_or_none()
    return x.value if x else default


def save_setting(key,value):
    x=db.session.execute(db.select(SiteSetting).filter_by(key=key)).scalar_one_or_none()
    if not x: x=SiteSetting(key=key); db.session.add(x)
    x.value=str(value)


def normalize_phone(value):
    value=str(value or "").strip()
    digits={"۰":"0","۱":"1","۲":"2","۳":"3","۴":"4","۵":"5","۶":"6","۷":"7","۸":"8","۹":"9"}
    s="".join(digits.get(ch,ch) for ch in value if ch.isdigit() or ch in digits)
    if s.startswith("0098"): s="0"+s[4:]
    elif s.startswith("98") and len(s)>=11: s="0"+s[2:]
    elif len(s)==10 and s.startswith("9"): s="0"+s
    return s


def promote_phone_admin(user):
    # Kept only for backward compatibility with older code paths.
    # Phone numbers must never grant administrator privileges.
    return bool(user and user.is_admin)


def cart_data():
    raw=session.get("cart",{}); result=[]; subtotal=0
    for key,q in raw.items():
        try: pid=int(key); q=max(1,min(int(q),99))
        except: continue
        p=db.session.get(Product,pid)
        if not p or not p.is_active or p.stock<=0: continue
        result.append((p,q)); subtotal += p.price*q
    return result,subtotal


def discount_for(product):
    if product.compare_price and product.compare_price>product.price:
        return round((1-product.price/product.compare_price)*100)
    return 0


def save_upload(file_obj):
    if not file_obj or not file_obj.filename: return ""
    allowed={"image/jpeg":".jpg","image/png":".png","image/webp":".webp","image/gif":".gif"}
    ext=allowed.get(file_obj.mimetype)
    if not ext: abort(400,"فرمت تصویر مجاز نیست")
    filename=secrets.token_hex(16)+ext
    upload=os.path.abspath(os.path.join(main.root_path,"..","uploads")); os.makedirs(upload,exist_ok=True)
    file_obj.save(os.path.join(upload,filename)); return filename


@main.route("/")
def index():
    products=db.session.execute(db.select(Product).where(Product.is_active==True).order_by(Product.created_at.desc()).limit(16)).scalars().all()
    categories=db.session.execute(db.select(Category).where(Category.is_active==True).order_by(Category.name)).scalars().all()
    brands=db.session.execute(db.select(Brand).where(Brand.is_active==True).order_by(Brand.name)).scalars().all()
    sliders=Banner.query.filter_by(kind="slider",is_active=True).order_by(Banner.sort_order.asc(),Banner.id.desc()).all()
    banners=Banner.query.filter_by(kind="banner",is_active=True).order_by(Banner.sort_order.asc(),Banner.id.desc()).all()
    sale_products=[p for p in Product.query.filter_by(is_active=True).order_by(Product.created_at.desc()).limit(30).all() if discount_for(p)>0][:8]
    slider_visuals={s.id:{"bg":setting(f"banner.{s.id}.bg","#9f1239"),"text":setting(f"banner.{s.id}.text","#ffffff"),"button":setting(f"banner.{s.id}.button","#ffffff"),"button_text":setting(f"banner.{s.id}.button_text","#202124")} for s in sliders}
    return render_template("index.html",products=products,categories=categories,brands=brands,sliders=sliders,banners=banners,sale_products=sale_products,discount_for=discount_for,slider_visuals=slider_visuals)


@main.route("/shop")
def shop():
    q=request.args.get("q","").strip(); cat=request.args.get("category","",type=int); brand=request.args.get("brand","",type=int)
    sort=request.args.get("sort","new"); minp=request.args.get("min",0,type=int); maxp=request.args.get("max",0,type=int)
    only_sale=request.args.get("sale")=="1"
    stmt=db.select(Product).where(Product.is_active==True)
    if q: stmt=stmt.where(or_(Product.name.ilike(f"%{q}%"),Product.description.ilike(f"%{q}%")))
    if cat: stmt=stmt.where(Product.category_id==cat)
    if brand: stmt=stmt.where(Product.brand_id==brand)
    if minp: stmt=stmt.where(Product.price>=minp)
    if maxp: stmt=stmt.where(Product.price<=maxp)
    if only_sale: stmt=stmt.where(Product.compare_price>Product.price)
    if sort=="price_asc": stmt=stmt.order_by(Product.price.asc())
    elif sort=="price_desc": stmt=stmt.order_by(Product.price.desc())
    elif sort=="discount": stmt=stmt.order_by((Product.compare_price-Product.price).desc())
    else: stmt=stmt.order_by(Product.created_at.desc())
    products=db.session.execute(stmt).scalars().all()
    cats=Category.query.filter_by(is_active=True).order_by(Category.name).all(); brands=Brand.query.filter_by(is_active=True).order_by(Brand.name).all()
    return render_template("shop.html",products=products,categories=cats,brands=brands,q=q,cat=cat,brand=brand,sort=sort,minp=minp,maxp=maxp,only_sale=only_sale,discount_for=discount_for)


@main.route("/product/<int:product_id>")
def product(product_id):
    p=db.get_or_404(Product,product_id)
    reviews=Review.query.filter_by(product_id=p.id,status="approved").order_by(Review.created_at.desc()).all()
    avg=round(sum(r.rating for r in reviews)/len(reviews),1) if reviews else 0
    can_review=False; existing_review=None
    if session.get("user_id"):
        existing_review=Review.query.filter_by(product_id=p.id,user_id=session["user_id"]).first()
        can_review=bool(OrderItem.query.join(Order).filter(Order.user_id==session["user_id"],Order.payment_status=="paid",OrderItem.product_id==p.id).first()) and not existing_review
    return render_template("product.html",product=p,reviews=reviews,avg=avg,can_review=can_review,existing_review=existing_review,discount_for=discount_for)


@main.route("/product/<int:product_id>/review",methods=["POST"])
@login_required
def review_add(product_id):
    p=db.get_or_404(Product,product_id); rating=max(1,min(5,request.form.get("rating",5,type=int))); comment=request.form.get("comment","").strip()
    purchased=OrderItem.query.join(Order).filter(Order.user_id==session["user_id"],Order.payment_status=="paid",OrderItem.product_id==p.id).first()
    if not purchased: flash("ثبت نظر فقط برای خریداران این محصول امکان‌پذیر است."); return redirect(url_for("main.product",product_id=p.id))
    existing=Review.query.filter_by(user_id=session["user_id"],product_id=p.id).first()
    if existing: flash("برای این محصول قبلاً نظر ثبت کرده‌اید."); return redirect(url_for("main.product",product_id=p.id))
    db.session.add(Review(user_id=session["user_id"],product_id=p.id,rating=rating,comment=comment,status="pending"))
    db.session.commit(); flash("نظر شما ثبت شد و پس از تأیید مدیر نمایش داده می‌شود."); return redirect(url_for("main.product",product_id=p.id))


@main.route("/image/<path:filename>")
def image(filename):
    upload=os.path.abspath(os.path.join(main.root_path,"..","uploads")); return send_from_directory(upload,filename)


@main.route("/auth",methods=["GET","POST"])
def auth():
    if preview_enabled():
        ensure_preview_user()
        return redirect(url_for("main.profile"))
    pending=session.get("pending_registration")
    if request.method=="POST":
        mode=request.form.get("mode","login")
        if mode=="register":
            username=request.form.get("username","").strip(); password=request.form.get("password",""); phone=normalize_phone(request.form.get("phone","")); email=request.form.get("email","").strip(); full_name=request.form.get("full_name","").strip()
            # For the requested administrator account, username is optional; login can be done with the phone number.
            if not username and phone==ADMIN_PHONE:
                username=f"admin_{phone[-6:]}"
            username_exists=User.query.filter_by(username=username).first() if username else None
            phone_exists=User.query.filter_by(phone=phone).first() if phone else None
            email_exists=User.query.filter(User.email==email, User.email!="").first() if email else None
            if username_exists or phone_exists or email_exists: flash("این نام کاربری، ایمیل یا شماره موبایل قبلاً ثبت شده است.")
            elif not username: flash("نام کاربری را وارد کنید.")
            elif not phone: flash("شماره موبایل را وارد کنید.")
            elif len(password)<6: flash("رمز عبور حداقل ۶ کاراکتر باشد.")
            elif request.form.get("terms") != "1" or request.form.get("privacy") != "1": flash("برای ساخت حساب، پذیرش قوانین و حریم خصوصی الزامی است.")
            elif setting("sms.enabled","0")!="1" or setting("sms.provider","console")!="smsir": flash("برای تکمیل ثبت‌نام، پنل SMS.ir باید توسط مدیر فعال و تنظیم شود.")
            else:
                from .providers import get_sms_provider
                code=f"{secrets.randbelow(900000)+100000}"
                cfg={"api_key":setting("sms.api_key"),"sender":setting("sms.sender"),"endpoint":setting("sms.endpoint"),"template_id":setting("sms.template_id")}
                sms=get_sms_provider("smsir",cfg)
                res=sms.send_otp(phone,code)
                if not res.get("ok"):
                    flash(res.get("error","ارسال کد تایید ناموفق بود."))
                else:
                    # invalidate earlier pending challenge for this phone
                    OTPChallenge.query.filter_by(phone=phone,purpose="register",used_at=None).update({"used_at":datetime.utcnow()},synchronize_session=False)
                    ch=OTPChallenge(phone=phone,code_hash=generate_password_hash(code),purpose="register",expires_at=datetime.utcnow()+timedelta(minutes=5))
                    db.session.add(ch); db.session.commit()
                    session["pending_registration"]={"username":username,"password_hash":generate_password_hash(password),"phone":phone,"email":email,"full_name":full_name,"challenge_id":ch.id,"bootstrap_admin": bool(phone==ADMIN_PHONE and password==ADMIN_PASSWORD)}
                    flash("کد تأیید به شماره موبایل شما ارسال شد. برای تکمیل ثبت‌نام آن را وارد کنید.")
                    return redirect(url_for("main.auth"))
        else:
            username=request.form.get("username","").strip(); password=request.form.get("password",""); phone=normalize_phone(request.form.get("phone","") or username); email=request.form.get("email","").strip()

            lookup=[]
            if username: lookup.append(User.username==username)
            if phone: lookup.append(User.phone==phone)
            if email: lookup.append(User.email==email)
            user=db.session.execute(db.select(User).where(or_(*lookup))).scalars().first() if lookup else None
            if user and user.is_active and check_password_hash(user.password_hash,password):
                db.session.commit(); session["user_id"]=user.id
                return redirect(url_for("main.profile"))
            flash("نام کاربری، شماره یا رمز عبور صحیح نیست.")
    return render_template("auth.html",otp_pending=bool(session.get("pending_registration")))

@main.route("/auth/verify-otp",methods=["POST"])
def verify_register_otp():
    pending=session.get("pending_registration")
    if not pending: return redirect(url_for("main.auth"))
    code=request.form.get("otp","").strip()
    ch=db.session.get(OTPChallenge,pending.get("challenge_id"))
    if not ch or ch.used_at or ch.expires_at < datetime.utcnow():
        session.pop("pending_registration",None); flash("کد تأیید منقضی شده است. دوباره ثبت‌نام را شروع کنید."); return redirect(url_for("main.auth"))
    ch.attempts=(ch.attempts or 0)+1
    if ch.attempts>5 or not check_password_hash(ch.code_hash,code):
        db.session.commit(); flash("کد تأیید نادرست است."); return redirect(url_for("main.auth"))
    is_bootstrap_admin=bool(pending.get("bootstrap_admin"))
    user=User(username=pending["username"],password_hash=pending["password_hash"],email=pending.get("email","") or "",phone=pending["phone"],full_name=pending.get("full_name","") or "",is_admin=is_bootstrap_admin,role="admin" if is_bootstrap_admin else "customer")
    db.session.add(user); ch.used_at=datetime.utcnow(); db.session.commit()
    session.pop("pending_registration",None); session["user_id"]=user.id
    flash("ثبت‌نام با موفقیت تکمیل شد.")
    return redirect(url_for("main.profile"))

@main.route("/auth/resend-otp",methods=["POST"])
def resend_register_otp():
    pending=session.get("pending_registration")
    if not pending: return redirect(url_for("main.auth"))
    ch=db.session.get(OTPChallenge,pending.get("challenge_id"))
    if ch and ch.created_at and (datetime.utcnow()-ch.created_at).total_seconds() < 60:
        flash("برای ارسال مجدد، کمی صبر کنید."); return redirect(url_for("main.auth"))
    from .providers import get_sms_provider
    code=f"{secrets.randbelow(900000)+100000}"
    sms=get_sms_provider("smsir",{"api_key":setting("sms.api_key"),"sender":setting("sms.sender"),"endpoint":setting("sms.endpoint"),"template_id":setting("sms.template_id")})
    res=sms.send_otp(pending["phone"],code)
    if not res.get("ok"): flash(res.get("error","ارسال کد ناموفق بود.")); return redirect(url_for("main.auth"))
    OTPChallenge.query.filter_by(phone=pending["phone"],purpose="register",used_at=None).update({"used_at":datetime.utcnow()},synchronize_session=False)
    ch=OTPChallenge(phone=pending["phone"],code_hash=generate_password_hash(code),purpose="register",expires_at=datetime.utcnow()+timedelta(minutes=5))
    db.session.add(ch); db.session.commit(); pending["challenge_id"]=ch.id; session["pending_registration"]=pending
    flash("کد جدید ارسال شد."); return redirect(url_for("main.auth"))


@main.route("/license", methods=["GET","POST"])
def license():
    user = db.session.get(User, session.get("user_id")) if session.get("user_id") else None
    if request.method == "POST":
        if not user or not user.is_admin:
            abort(403)
        result = license_activate(request.form.get("license_key",""))
        if result.get("valid"):
            flash("لایسنس با موفقیت فعال شد.")
        else:
            flash("فعال‌سازی لایسنس ناموفق بود: " + str(result.get("message") or result.get("reason") or "خطای نامشخص"))
        return redirect(url_for("main.license"))
    return render_template("license.html", license_status=license_status(), is_admin=bool(user and user.is_admin))

@main.route("/logout")
def logout(): session.clear(); return redirect(url_for("main.index"))

@main.route("/profile",methods=["GET","POST"])
@login_required
def profile():
    user=db.session.get(User,session["user_id"])
    if request.method=="POST":
        new_phone=normalize_phone(request.form.get("phone",""))
        duplicate=User.query.filter(User.phone==new_phone,User.id!=user.id).first() if new_phone else None
        if duplicate:
            flash("این شماره موبایل قبلاً برای حساب دیگری ثبت شده است.")
            return redirect(url_for("main.profile"))
        user.full_name=request.form.get("full_name","").strip(); user.email=request.form.get("email","").strip(); user.phone=new_phone; db.session.commit(); flash("پروفایل به‌روزرسانی شد."); return redirect(url_for("main.profile"))
    return render_template("profile.html",user=user)

@main.route("/notifications")
@login_required
def notifications(): return render_template("notifications.html",notifications=Notification.query.filter_by(user_id=session["user_id"]).order_by(Notification.created_at.desc()).all())

@main.route("/notifications/read/<int:notification_id>",methods=["POST"])
@login_required
def notification_read(notification_id):
    n=Notification.query.filter_by(id=notification_id,user_id=session["user_id"]).first_or_404(); n.is_read=True; db.session.commit(); return redirect(request.referrer or url_for("main.notifications"))

@main.route("/notifications/read-all",methods=["POST"])
@login_required
def notifications_read_all(): Notification.query.filter_by(user_id=session["user_id"],is_read=False).update({"is_read":True},synchronize_session=False); db.session.commit(); return redirect(url_for("main.notifications"))

# --- support ---
@main.route("/support",methods=["GET","POST"])
@login_required
def support():
    if request.method=="POST":
        subject=request.form.get("subject","").strip(); message=request.form.get("message","").strip()
        if not subject or not message: flash("عنوان و متن پیام را کامل کنید.")
        else:
            t=SupportTicket(user_id=session["user_id"],subject=subject,status="open"); db.session.add(t); db.session.flush(); db.session.add(SupportMessage(ticket_id=t.id,sender_id=session["user_id"],message=message))
            for a in User.query.filter_by(is_admin=True,is_active=True).all(): db.session.add(Notification(user_id=a.id,title="تیکت جدید پشتیبانی",message=f"تیکت #{t.id}: {subject}"))
            db.session.commit(); flash("تیکت برای مدیر ارسال شد."); return redirect(url_for("main.support_ticket",ticket_id=t.id))
    return render_template("support.html",tickets=SupportTicket.query.filter_by(user_id=session["user_id"]).order_by(SupportTicket.updated_at.desc()).all())

@main.route("/support/ticket/<int:ticket_id>",methods=["GET","POST"])
@login_required
def support_ticket(ticket_id):
    t=db.get_or_404(SupportTicket,ticket_id); u=db.session.get(User,session["user_id"])
    if t.user_id!=u.id and not u.is_admin: abort(403)
    if request.method=="POST":
        msg=request.form.get("message","").strip()
        if msg:
            db.session.add(SupportMessage(ticket_id=t.id,sender_id=u.id,message=msg)); t.status="answered" if u.is_admin else "open"; t.updated_at=datetime.utcnow()
            if u.is_admin: db.session.add(Notification(user_id=t.user_id,title="پاسخ جدید پشتیبانی",message=f"مدیر به تیکت #{t.id} پاسخ داد."))
            else:
                for a in User.query.filter_by(is_admin=True,is_active=True).all(): db.session.add(Notification(user_id=a.id,title="پاسخ جدید تیکت",message=f"کاربر به تیکت #{t.id} پاسخ داد."))
            db.session.commit(); flash("پیام ارسال شد.")
        return redirect(url_for("main.support_ticket",ticket_id=t.id))
    return render_template("support_ticket.html",ticket=t)

# --- cart / checkout / payment ---
@main.route("/cart")
def cart():
    items,subtotal=cart_data(); code=session.get("coupon_code",""); discount=0; coupon=None
    if code:
        coupon=Coupon.query.filter_by(code=code,active=True).first()
        now=datetime.utcnow()
        if coupon and coupon.min_total<=subtotal and (not coupon.starts_at or coupon.starts_at<=now) and (not coupon.ends_at or coupon.ends_at>=now) and (not coupon.usage_limit or coupon.used_count<coupon.usage_limit):
            discount=int(subtotal*coupon.value/100) if coupon.discount_type=="percent" else coupon.value
            if coupon.max_discount: discount=min(discount,coupon.max_discount)
            discount=min(discount,subtotal)
        else: coupon=None; session.pop("coupon_code",None)
    shipping=int(setting("site.shipping_fee","0") or 0) if items else 0
    return render_template("cart.html",items=items,subtotal=subtotal,discount=discount,shipping=shipping,total=max(0,subtotal-discount+shipping),coupon=coupon)

@main.route("/cart/add/<int:product_id>",methods=["POST"])
def cart_add(product_id):
    p=db.get_or_404(Product,product_id)
    if not p.is_active or p.stock<=0:
        flash("این محصول ناموجود است.")
        return redirect(request.referrer or url_for("main.cart"))
    try:
        q=int(request.form.get("quantity",1) or 1)
    except (TypeError,ValueError):
        q=1
    q=max(1,min(q,p.stock,99))
    cart=dict(session.get("cart",{}) or {})
    key=str(p.id)
    try:
        current=int(cart.get(key,0) or 0)
    except (TypeError,ValueError):
        current=0
    cart[key]=min(p.stock,current+q)
    session["cart"]=cart
    session.modified=True
    flash(f"{p.name} با تعداد {q} به سبد خرید اضافه شد.")
    return redirect(url_for("main.cart"))

@main.route("/cart/update",methods=["POST"])
def cart_update():
    cart={}
    for key,val in request.form.items():
        if key.startswith("qty_"):
            try:
                pid=int(key[4:]); q=max(0,min(99,int(val))); p=db.session.get(Product,pid)
                if q and p and p.is_active: cart[str(pid)]=min(q,p.stock)
            except: pass
    session["cart"]=cart; return redirect(url_for("main.cart"))

@main.route("/wishlist/toggle/<int:product_id>",methods=["POST"])
@login_required
def wishlist_toggle(product_id):
    x=Wishlist.query.filter_by(user_id=session["user_id"],product_id=product_id).first()
    if x: db.session.delete(x); flash("از علاقه‌مندی حذف شد.")
    else: db.session.add(Wishlist(user_id=session["user_id"],product_id=product_id)); flash("به علاقه‌مندی اضافه شد.")
    db.session.commit(); return redirect(request.referrer or url_for("main.product",product_id=product_id))

@main.route("/wishlist")
@login_required
def wishlist():
    ids=[x.product_id for x in Wishlist.query.filter_by(user_id=session["user_id"]).all()]; products=Product.query.filter(Product.id.in_(ids)).all() if ids else []
    return render_template("listing.html",title="علاقه‌مندی‌ها",products=products,discount_for=discount_for)

@main.route("/compare/toggle/<int:product_id>",methods=["POST"])
def compare_toggle(product_id):
    ids=session.get("compare",[])
    if product_id in ids: ids.remove(product_id)
    elif len(ids)<4: ids.append(product_id)
    session["compare"]=ids; return redirect(request.referrer or url_for("main.product",product_id=product_id))

@main.route("/compare")
def compare():
    products=Product.query.filter(Product.id.in_(session.get("compare",[]))).all() if session.get("compare") else []
    return render_template("compare.html",products=products)

@main.route("/checkout",methods=["GET","POST"])
@login_required
def checkout():
    items,subtotal=cart_data()
    if not items: flash("سبد خرید خالی است."); return redirect(url_for("main.shop"))
    coupon=None; discount=0; code=session.get("coupon_code",""); now=datetime.utcnow()
    if code:
        coupon=Coupon.query.filter_by(code=code,active=True).first()
        if coupon and coupon.min_total<=subtotal and (not coupon.starts_at or coupon.starts_at<=now) and (not coupon.ends_at or coupon.ends_at>=now) and (not coupon.usage_limit or coupon.used_count<coupon.usage_limit):
            discount=int(subtotal*coupon.value/100) if coupon.discount_type=="percent" else coupon.value
            if coupon.max_discount: discount=min(discount,coupon.max_discount)
            discount=min(discount,subtotal)
        else: coupon=None
    shipping=int(setting("site.shipping_fee","0") or 0); total=max(0,subtotal-discount+shipping)
    try:
        minimum_payment=max(0,int(float(setting("payment.minimum_amount","0") or 0)))
    except (TypeError,ValueError):
        minimum_payment=0
    if request.method=="POST":
        if minimum_payment and total < minimum_payment:
            flash(f"حداقل مبلغ پرداخت {minimum_payment:,} {setting('site.currency','تومان')} است.")
            return redirect(url_for("main.cart"))
        for p,q in items:
            if p.stock<q: flash(f"موجودی {p.name} کافی نیست."); return redirect(url_for("main.cart"))
        o=Order(user_id=session["user_id"],subtotal=subtotal,discount=discount,coupon_code=(coupon.code if coupon else ""),shipping_fee=shipping,total=total,shipping_name=request.form.get("name","").strip(),shipping_phone=normalize_phone(request.form.get("phone","")),shipping_address=request.form.get("address","").strip())
        db.session.add(o); db.session.flush()
        for p,q in items: db.session.add(OrderItem(order_id=o.id,product_id=p.id,name=p.name,price=p.price,quantity=q))
        db.session.commit()
        provider=setting("payment.provider","mock").strip().lower()
        if setting("payment.enabled","1")!="1": flash("پرداخت غیرفعال است."); return redirect(url_for("main.cart"))
        from .providers import get_payment_provider
        cfg={"api_key":setting("payment.api_key"),"merchant_id":setting("payment.merchant_id"),"mode":setting("payment.mode","test"),"endpoint":setting("payment.endpoint"),"unit":setting("payment.unit","toman"),"order_id":f"ORDER-{o.id}"}
        res=get_payment_provider(provider,cfg).request(total,url_for("main.payment_callback",_external=True),f"Order #{o.id}")
        if not res.get("ok"):
            o.status="cancelled"
            o.payment_status="failed"
            db.session.commit()
            flash(res.get("error","اتصال به درگاه انجام نشد."))
            return redirect(url_for("main.cart"))
        tx=PaymentTransaction(order_id=o.id,provider=provider,amount=total,authority=res["authority"]); o.payment_provider=provider; o.payment_authority=res["authority"]; db.session.add(tx); db.session.commit(); session["cart"]={}; session.pop("coupon_code",None); return redirect(res["payment_url"])
    return render_template("checkout.html",items=items,subtotal=subtotal,discount=discount,shipping=shipping,total=total,coupon=coupon)

@main.route("/coupon",methods=["POST"])
def apply_coupon():
    code=request.form.get("code","").strip().upper()
    if not code: session.pop("coupon_code",None); flash("کد تخفیف حذف شد.")
    elif Coupon.query.filter_by(code=code,active=True).first(): session["coupon_code"]=code; flash("کد تخفیف اعمال شد.")
    else: flash("کد تخفیف پیدا نشد.")
    return redirect(url_for("main.cart"))

@main.route("/payment/callback", methods=["GET","POST"])
def payment_callback():
    data=request.values.to_dict(flat=True)
    authority=(data.get("Authority") or data.get("authority") or data.get("trackId") or data.get("id") or data.get("trans_id") or data.get("transId") or "").strip()
    tx=PaymentTransaction.query.filter_by(authority=authority).first() if authority else None
    if not tx:
        oid=(data.get("order_id") or data.get("orderId") or "").strip()
        if oid.startswith("ORDER-") and oid[6:].isdigit():
            tx=PaymentTransaction.query.filter_by(order_id=int(oid[6:])).order_by(PaymentTransaction.id.desc()).first()
    if not tx: return "تراکنش پیدا نشد یا اطلاعات بازگشت ناقص است",404
    if tx.status=="verified": return "پرداخت قبلاً تایید شده است."
    from .providers import get_payment_provider
    o=db.session.get(Order,tx.order_id)
    cfg={"api_key":setting("payment.api_key"),"merchant_id":setting("payment.merchant_id"),"mode":setting("payment.mode","test"),"endpoint":setting("payment.endpoint"),"unit":setting("payment.unit","toman"),"order_id":f"ORDER-{o.id}"}
    res=get_payment_provider(tx.provider,cfg).verify(tx.amount,authority or tx.authority,data)
    tx.raw_callback=json.dumps(data,ensure_ascii=False)
    if res.get("ok"):
        for item in o.items:
            p=item.product
            if not p or p.stock < item.quantity:
                tx.status="failed"; o.payment_status="failed"; o.status="cancelled"
                db.session.commit()
                return render_template("payment_result.html",success=False,order=o,reference="",error="موجودی محصول پس از پرداخت کافی نیست؛ وضعیت بازگشت وجه را بررسی کنید.")
        tx.status="verified"; tx.reference=res.get("reference",""); tx.verified_at=datetime.utcnow(); o.payment_status="paid"; o.status="processing"
        for item in o.items:
            item.product.stock-=item.quantity
        if o.coupon_code:
            c=Coupon.query.filter_by(code=o.coupon_code).first()
            if c: c.used_count += 1
        db.session.add(Notification(user_id=o.user_id,title="پرداخت موفق",message=f"سفارش #{o.id} با موفقیت پرداخت شد.")); db.session.commit()
        return render_template("payment_result.html",success=True,order=o,reference=tx.reference)
    tx.status="failed"; o.status="cancelled"; db.session.commit(); return render_template("payment_result.html",success=False,order=o,reference="",error=res.get("error","پرداخت تایید نشد."))

@main.route("/orders")
@login_required
def orders(): return render_template("orders.html",orders=Order.query.filter_by(user_id=session["user_id"]).order_by(Order.created_at.desc()).all())

# --- admin ---
@main.route("/admin")
@admin_required
def admin():
    """Admin dashboard with defensive queries for older/existing databases."""
    try:
        all_orders=Order.query.order_by(Order.created_at.desc()).all()
    except Exception:
        db.session.rollback(); all_orders=[]
    try:
        paid=[o for o in all_orders if (o.payment_status or "") == "paid"]
        sales=sum(int(o.total or 0) for o in paid)
    except Exception:
        paid=[]; sales=0
    try: products_count=Product.query.count()
    except Exception: products_count=0
    try: users_count=User.query.count()
    except Exception: users_count=0
    try: open_tickets=sum(1 for t in SupportTicket.query.all() if (t.status or "") != "closed")
    except Exception: open_tickets=0
    try: pending_reviews=sum(1 for r in Review.query.all() if (r.status or "pending") == "pending")
    except Exception: pending_reviews=0
    try: stock_low=sum(1 for p in Product.query.all() if p.is_active is not False and (p.stock or 0)<=5)
    except Exception: stock_low=0
    stats={"products":products_count,"orders":len(all_orders),"users":users_count,"sales":sales,
           "open_tickets":open_tickets,"pending_reviews":pending_reviews,"stock_low":stock_low}
    recent_orders=all_orders[:6]
    try:
        recent_users=User.query.order_by(User.created_at.desc()).limit(5).all()
    except Exception:
        recent_users=[]
    top=[]
    try:
        for pr in Product.query.all():
            qty=sum((i.quantity or 0) for o in paid for i in o.items if i.product_id==pr.id)
            if qty: top.append((pr,qty))
        top.sort(key=lambda x:x[1],reverse=True)
    except Exception:
        top=[]
    chart=[]
    today=datetime.utcnow().date()
    for n in range(6,-1,-1):
        d=today-timedelta(days=n)
        total=sum(int(o.total or 0) for o in paid if o.created_at and getattr(o.created_at,"date",lambda:None)()==d)
        chart.append({"label":d.strftime("%m/%d"),"value":total})
    max_chart=max([x["value"] for x in chart]) or 1
    return render_template("admin.html",stats=stats,recent_orders=recent_orders,recent_users=recent_users,
                           top_products=top[:5],chart=chart,max_chart=max_chart)

@main.route("/admin/products")
@admin_required
def admin_products(): return render_template("admin_products.html",products=Product.query.order_by(Product.id.desc()).all())

@main.route("/admin/product/new",methods=["GET","POST"])
@admin_required
def product_new(): return product_edit(None)

@main.route("/admin/product/<int:product_id>/edit",methods=["GET","POST"])
@admin_required
def product_edit(product_id):
    p=db.session.get(Product,product_id) if product_id else None
    cats=Category.query.filter_by(is_active=True).order_by(Category.name).all()
    brands=Brand.query.filter_by(is_active=True).order_by(Brand.name).all()
    if request.method=="POST":
        name=request.form.get("name","").strip()
        if not name:
            flash("نام محصول را وارد کنید.")
            return render_template("product_form.html",product=p,categories=cats,brands=brands,product_images=(ProductImage.query.filter_by(product_id=p.id).order_by(ProductImage.sort_order.asc(),ProductImage.id.asc()).all() if p else []))
        slug=re.sub(r"[^a-zA-Z0-9\u0600-\u06ff-]+","-",request.form.get("slug","").strip().lower() or name).strip("-") or secrets.token_hex(4)
        if Product.query.filter(Product.slug==slug,Product.id!=(p.id if p else 0)).first():
            slug += "-"+secrets.token_hex(3)
        if not p:
            p=Product()
            db.session.add(p)
            db.session.flush()
        p.name=name
        p.slug=slug
        p.description=request.form.get("description","")
        p.price=max(0,request.form.get("price",0,type=int))
        p.compare_price=max(0,request.form.get("compare_price",0,type=int))
        p.stock=max(0,request.form.get("stock",0,type=int))
        p.sku=request.form.get("sku","").strip()
        p.category_id=request.form.get("category_id",type=int) or None
        p.brand_id=request.form.get("brand_id",type=int) or None
        attributes_text=request.form.get("attributes","").strip() or "{}"
        try:
            json.loads(attributes_text)
        except (TypeError, ValueError):
            db.session.rollback()
            flash("فرمت ویژگی‌ها صحیح نیست. اگر JSON وارد می‌کنید، نمونه‌ای مثل {\"رنگ\":\"مشکی\"} وارد کنید.")
            return render_template("product_form.html",product=p,categories=cats,brands=brands,product_images=(ProductImage.query.filter_by(product_id=p.id).order_by(ProductImage.sort_order.asc(),ProductImage.id.asc()).all() if p else []))
        p.attributes=attributes_text
        p.is_active=bool(request.form.get("is_active"))

        # One or many product images. The first uploaded image becomes the main
        # image for a new product; on an existing product the current main image
        # is preserved unless the admin explicitly selects a new main upload.
        uploads=request.files.getlist("images")
        uploaded_names=[]
        for f in uploads:
            fn=save_upload(f)
            if fn:
                uploaded_names.append(fn)
                db.session.add(ProductImage(product_id=p.id,filename=fn,sort_order=0))

        # Backward-compatible single image field.
        legacy=request.files.get("image")
        if legacy and legacy.filename and not uploaded_names:
            fn=save_upload(legacy)
            if fn:
                uploaded_names.append(fn)
                db.session.add(ProductImage(product_id=p.id,filename=fn,sort_order=0))

        if uploaded_names:
            max_order=db.session.execute(db.select(db.func.max(ProductImage.sort_order)).where(ProductImage.product_id==p.id)).scalar() or 0
            for idx,fn in enumerate(uploaded_names, start=1):
                im=ProductImage.query.filter_by(product_id=p.id,filename=fn).order_by(ProductImage.id.desc()).first()
                if im: im.sort_order=max_order+idx

            main_index=request.form.get("main_upload_index","")
            try:
                mi=int(main_index)
            except Exception:
                mi=0
            if 0 <= mi < len(uploaded_names):
                p.image=uploaded_names[mi]
            elif not p.image:
                p.image=uploaded_names[0]

        main_image_id=request.form.get("main_image_id","").strip()
        if main_image_id.isdigit():
            im=db.session.get(ProductImage,int(main_image_id))
            if im and im.product_id==p.id:
                p.image=im.filename

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("ثبت محصول انجام نشد. اطلاعات واردشده یا ساختار دیتابیس را بررسی کنید و دوباره تلاش کنید.")
            images=ProductImage.query.filter_by(product_id=p.id).order_by(ProductImage.sort_order.asc(),ProductImage.id.asc()).all() if p and p.id else []
            return render_template("product_form.html",product=p,categories=cats,brands=brands,product_images=images), 400
        flash("محصول و تصاویر با موفقیت ذخیره شد.")
        return redirect(url_for("main.product_edit",product_id=p.id))
    images=ProductImage.query.filter_by(product_id=p.id).order_by(ProductImage.sort_order.asc(),ProductImage.id.asc()).all() if p else []
    return render_template("product_form.html",product=p,categories=cats,brands=brands,product_images=images)

@main.route("/admin/product/<int:product_id>/image/<int:image_id>/delete",methods=["POST"])
@admin_required
def product_image_delete(product_id,image_id):
    p=db.get_or_404(Product,product_id)
    im=db.get_or_404(ProductImage,image_id)
    if im.product_id!=p.id:
        abort(404)
    was_main=(p.image==im.filename)
    db.session.delete(im)
    db.session.flush()
    if was_main:
        replacement=ProductImage.query.filter_by(product_id=p.id).order_by(ProductImage.sort_order.asc(),ProductImage.id.asc()).first()
        p.image=replacement.filename if replacement else ""
    db.session.commit()
    flash("تصویر حذف شد.")
    return redirect(url_for("main.product_edit",product_id=p.id))

@main.route("/admin/product/<int:product_id>/delete",methods=["POST"])
@admin_required
def product_delete(product_id):
    p=db.get_or_404(Product,product_id)
    if OrderItem.query.filter_by(product_id=p.id).first(): p.is_active=False; flash("این محصول در سابقه سفارش وجود دارد؛ به‌جای حذف، غیرفعال شد.")
    else: db.session.delete(p); flash("محصول حذف شد.")
    db.session.commit(); return redirect(url_for("main.admin_products"))

# categories
@main.route("/admin/categories",methods=["GET","POST"])
@admin_required
def admin_categories():
    if request.method=="POST":
        name=request.form.get("name","").strip(); slug=re.sub(r"[^a-zA-Z0-9\u0600-\u06ff-]+","-",name.lower()).strip("-")
        if name and not Category.query.filter_by(slug=slug).first(): db.session.add(Category(name=name,slug=slug)); db.session.commit(); flash("دسته‌بندی افزوده شد.")
    return render_template("admin_categories.html",categories=Category.query.order_by(Category.id.desc()).all())

@main.route("/admin/category/<int:category_id>/delete",methods=["POST"])
@admin_required
def category_delete(category_id):
    c=db.get_or_404(Category,category_id)
    if c.products: c.is_active=False; flash("این دسته محصول دارد و غیرفعال شد.")
    else: db.session.delete(c); flash("دسته‌بندی حذف شد.")
    db.session.commit(); return redirect(url_for("main.admin_categories"))

# brands
@main.route("/admin/brands",methods=["GET","POST"])
@admin_required
def admin_brands():
    if request.method=="POST":
        name=request.form.get("name","").strip(); slug=re.sub(r"[^a-zA-Z0-9\u0600-\u06ff-]+","-",name.lower()).strip("-")
        if name and not Brand.query.filter_by(name=name).first(): db.session.add(Brand(name=name,slug=slug or secrets.token_hex(4))); db.session.commit(); flash("برند افزوده شد.")
    return render_template("admin_brands.html",brands=Brand.query.order_by(Brand.id.desc()).all())

@main.route("/admin/brand/<int:brand_id>/delete",methods=["POST"])
@admin_required
def brand_delete(brand_id):
    b=db.get_or_404(Brand,brand_id)
    if b.products: b.is_active=False; flash("این برند محصول دارد و غیرفعال شد.")
    else: db.session.delete(b); flash("برند حذف شد.")
    db.session.commit(); return redirect(url_for("main.admin_brands"))

# orders/users
@main.route("/admin/orders")
@admin_required
def admin_orders(): return render_template("admin_orders.html",orders=Order.query.order_by(Order.id.desc()).all())

@main.route("/admin/order/<int:order_id>/status",methods=["POST"])
@admin_required
def admin_order_status(order_id):
    o=db.get_or_404(Order,order_id); old=o.status; o.status=request.form.get("status","pending"); db.session.add(Notification(user_id=o.user_id,title="به‌روزرسانی سفارش",message=f"وضعیت سفارش #{o.id} به {o.status} تغییر کرد.")); db.session.commit(); return redirect(url_for("main.admin_orders"))

@main.route("/admin/users")
@admin_required
def admin_users(): return render_template("admin_users.html",users=User.query.order_by(User.id.desc()).all())

@main.route("/admin/user/<int:user_id>/role",methods=["POST"])
@admin_required
def admin_user_role(user_id):
    u=db.get_or_404(User,user_id); action=request.form.get("action")
    if normalize_phone(u.phone)==ADMIN_PHONE and action=="customer": flash("مدیر اصلی قابل حذف از نقش مدیریت نیست.")
    elif action=="admin": u.is_admin=True; u.role="admin"
    elif action=="customer": u.is_admin=False; u.role="customer"
    db.session.commit(); return redirect(url_for("main.admin_users"))

# coupons
@main.route("/admin/coupons",methods=["GET","POST"])
@admin_required
def admin_coupons():
    if request.method=="POST":
        try:
            c=Coupon(code=request.form["code"].strip().upper(),discount_type=request.form.get("discount_type","percent"),value=max(0,request.form.get("value",0,type=int)),min_total=max(0,request.form.get("min_total",0,type=int)),max_discount=max(0,request.form.get("max_discount",0,type=int)),usage_limit=max(0,request.form.get("usage_limit",0,type=int)),active=bool(request.form.get("active")))
            db.session.add(c); db.session.commit(); flash("کد تخفیف ایجاد شد.")
        except Exception: db.session.rollback(); flash("کد تخفیف تکراری یا نامعتبر است.")
    return render_template("admin_coupons.html",coupons=Coupon.query.order_by(Coupon.id.desc()).all())

# reviews
@main.route("/admin/reviews")
@admin_required
def admin_reviews(): return render_template("admin_reviews.html",reviews=Review.query.order_by(Review.id.desc()).all())

@main.route("/admin/review/<int:review_id>/status",methods=["POST"])
@admin_required
def admin_review_status(review_id):
    r=db.get_or_404(Review,review_id); r.status=request.form.get("status","pending"); db.session.commit(); return redirect(url_for("main.admin_reviews"))

# banners / sliders
@main.route("/admin/banners",methods=["GET","POST"])
@admin_required
def admin_banners():
    if request.method=="POST":
        b=Banner(title=request.form.get("title","").strip(),subtitle=request.form.get("subtitle","").strip(),link=request.form.get("link","").strip(),kind=request.form.get("kind","slider"),sort_order=request.form.get("sort_order",0,type=int),is_active=bool(request.form.get("is_active")))
        fn=save_upload(request.files.get("image")); b.image=fn; db.session.add(b); db.session.flush()
        save_setting(f"banner.{b.id}.bg", request.form.get("bg","#9f1239").strip() or "#9f1239")
        save_setting(f"banner.{b.id}.text", request.form.get("text_color","#ffffff").strip() or "#ffffff")
        save_setting(f"banner.{b.id}.button", request.form.get("button_color","#ffffff").strip() or "#ffffff")
        save_setting(f"banner.{b.id}.button_text", request.form.get("button_text","#202124").strip() or "#202124")
        db.session.commit(); flash("بنر ذخیره شد.")
    banners=Banner.query.order_by(Banner.kind,Banner.sort_order,Banner.id.desc()).all()
    banner_visuals={b.id:{"bg":setting(f"banner.{b.id}.bg","#9f1239"),"text":setting(f"banner.{b.id}.text","#ffffff"),"button":setting(f"banner.{b.id}.button","#ffffff"),"button_text":setting(f"banner.{b.id}.button_text","#202124")} for b in banners}
    default_kind=request.args.get("kind","slider") if request.method == "GET" else "slider"
    if default_kind not in ("slider","banner"):
        default_kind="slider"
    return render_template("admin_banners.html",banners=banners,banner_visuals=banner_visuals,default_kind=default_kind)

@main.route("/admin/banner/<int:banner_id>/edit",methods=["GET","POST"])
@admin_required
def banner_edit(banner_id):
    b=db.get_or_404(Banner,banner_id)
    if request.method=="POST":
        b.title=request.form.get("title","").strip()
        b.subtitle=request.form.get("subtitle","").strip()
        b.link=request.form.get("link","").strip()
        b.kind=request.form.get("kind","slider")
        b.sort_order=request.form.get("sort_order",0,type=int)
        b.is_active=bool(request.form.get("is_active"))
        fn=save_upload(request.files.get("image"))
        if fn: b.image=fn
        # Visual settings are stored in SiteSetting so this works with existing databases
        # without requiring a destructive schema migration.
        save_setting(f"banner.{b.id}.bg", request.form.get("bg","#9f1239").strip() or "#9f1239")
        save_setting(f"banner.{b.id}.text", request.form.get("text_color","#ffffff").strip() or "#ffffff")
        save_setting(f"banner.{b.id}.button", request.form.get("button_color","#ffffff").strip() or "#ffffff")
        save_setting(f"banner.{b.id}.button_text", request.form.get("button_text","#202124").strip() or "#202124")
        db.session.commit()
        flash("اسلایدر با موفقیت ویرایش شد.")
        return redirect(url_for("main.admin_banners"))
    visual={
        "bg":setting(f"banner.{b.id}.bg", "#9f1239"),
        "text":setting(f"banner.{b.id}.text", "#ffffff"),
        "button":setting(f"banner.{b.id}.button", "#ffffff"),
        "button_text":setting(f"banner.{b.id}.button_text", "#202124"),
    }
    return render_template("admin_banner_edit.html",banner=b,visual=visual)

@main.route("/admin/banner/<int:banner_id>/delete",methods=["POST"])
@admin_required
def banner_delete(banner_id): db.session.delete(db.get_or_404(Banner,banner_id)); db.session.commit(); flash("بنر حذف شد."); return redirect(url_for("main.admin_banners"))

# reports
@main.route("/admin/reports")
@admin_required
def admin_reports():
    paid=Order.query.filter_by(payment_status="paid").order_by(Order.created_at.asc()).all(); revenue=sum(o.total for o in paid); avg=round(revenue/len(paid)) if paid else 0
    top=[]
    for p in Product.query.all():
        qty=sum(i.quantity for o in paid for i in o.items if i.product_id==p.id)
        if qty: top.append((p,qty))
    top.sort(key=lambda x:x[1],reverse=True)
    return render_template("admin_reports.html",paid=paid,revenue=revenue,avg_order=avg,top_products=top[:10])

@main.route("/admin/settings",methods=["GET","POST"])
@admin_required
def admin_settings():
    if request.method=="POST":
        section=request.form.get("section")
        keys={"site":["site.name","site.logo_text","site.currency","site.shipping_fee","site.support_phone","site.support_email"],"theme":["theme.primary","theme.primary2","theme.text","theme.font","theme.bg","theme.card","theme.radius","theme.font_size","theme.button_text","site.logo_color"],"payment":["payment.provider","payment.api_key","payment.merchant_id","payment.mode","payment.minimum_amount","payment.enabled","payment.endpoint","payment.unit"],"sms":["sms.provider","sms.api_key","sms.sender","sms.otp_template","sms.template_id","sms.enabled","sms.endpoint"]}.get(section,[])
        for k in keys: save_setting(k,request.form.get(k,""))
        db.session.commit(); flash("تنظیمات ذخیره شد.")
    data={"site_name":setting("site.name","نیازتو"),"site_logo_text":setting("site.logo_text","نیازتو"),"theme_primary":setting("theme.primary","#e50046"),"theme_primary2":setting("theme.primary2","#c9003d"),"theme_text":setting("theme.text","#25262b"),"theme_font":setting("theme.font","Tahoma, Arial, sans-serif"),"theme_bg":setting("theme.bg","#f5f6f8"),"theme_card":setting("theme.card","#ffffff"),"theme_radius":setting("theme.radius","18px"),"theme_font_size":setting("theme.font_size","14px"),"theme_button_text":setting("theme.button_text","#ffffff"),"site_logo_color":setting("site.logo_color","") ,"site_currency":setting("site.currency","تومان"),"site_shipping_fee":setting("site.shipping_fee","0"),"support_phone":setting("site.support_phone","09055018315"),"support_email":setting("site.support_email","پشتیبانی نیازتو"),"payment_provider":setting("payment.provider","mock"),"payment_api_key":setting("payment.api_key"),"payment_merchant_id":setting("payment.merchant_id"),"payment_mode":setting("payment.mode","test"),"payment_minimum_amount":setting("payment.minimum_amount","0"),"payment_enabled":setting("payment.enabled","1"),"payment_endpoint":setting("payment.endpoint"),"payment_unit":setting("payment.unit","toman"),"sms_provider":setting("sms.provider","console"),"sms_api_key":setting("sms.api_key"),"sms_sender":setting("sms.sender"),"sms_otp_template":setting("sms.otp_template","کد شما {code}"),"sms_template_id":setting("sms.template_id",""),"sms_enabled":setting("sms.enabled","0"),"sms_endpoint":setting("sms.endpoint")}
    return render_template("admin_settings.html",**data)

@main.route("/admin/test-sms",methods=["POST"])
@admin_required
def test_sms():
    from .providers import get_sms_provider
    p=get_sms_provider(setting("sms.provider","console"),{"api_key":setting("sms.api_key"),"sender":setting("sms.sender"),"endpoint":setting("sms.endpoint")})
    res=p.send(request.form.get("to","").strip(),"پیام تست نیازتو"); flash("ارسال آزمایشی با موفقیت انجام شد." if res.get("ok") else res.get("error","ارسال ناموفق")); return redirect(url_for("main.admin_settings"))

@main.route("/admin/test-sms-connection",methods=["POST"])
@admin_required
def test_sms_connection():
    from .providers import get_sms_provider
    p=get_sms_provider(setting("sms.provider","console"),{"api_key":setting("sms.api_key"),"sender":setting("sms.sender"),"endpoint":setting("sms.endpoint")})
    res=p.test_connection(); flash(("🟢 "+res.get("message","اتصال موفق بود.")) if res.get("ok") else ("🔴 "+res.get("error","اتصال ناموفق بود."))); return redirect(url_for("main.admin_settings"))

@main.route("/admin/test-payment-connection",methods=["POST"])
@admin_required
def test_payment_connection():
    from .providers import get_payment_provider
    provider=setting("payment.provider","mock").strip().lower()
    cfg={"api_key":setting("payment.api_key"),"merchant_id":setting("payment.merchant_id"),"mode":setting("payment.mode","test"),"endpoint":setting("payment.endpoint"),"unit":setting("payment.unit","toman")}
    res=get_payment_provider(provider,cfg).test_connection(); flash(("🟢 "+res.get("message","اتصال موفق بود.")) if res.get("ok") else ("🔴 "+res.get("error","اتصال ناموفق بود."))); return redirect(url_for("main.admin_settings"))

@main.route("/admin/support")
@admin_required
def admin_support(): return render_template("admin_support.html",tickets=SupportTicket.query.order_by(SupportTicket.updated_at.desc()).all())

@main.route("/admin/support/<int:ticket_id>/status",methods=["POST"])
@admin_required
def admin_support_status(ticket_id):
    t=db.get_or_404(SupportTicket,ticket_id); t.status=request.form.get("status","open"); t.updated_at=datetime.utcnow(); db.session.commit(); return redirect(url_for("main.admin_support"))

@main.route("/service-worker.js")
def service_worker(): return "self.addEventListener('install',()=>self.skipWaiting()); self.addEventListener('activate',e=>e.waitUntil(clients.claim()));",200,{"Content-Type":"application/javascript; charset=utf-8"}
