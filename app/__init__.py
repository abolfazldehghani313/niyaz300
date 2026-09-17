import os
from flask import Flask, session
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from sqlalchemy import inspect, text
load_dotenv()

db=SQLAlchemy()


def _add_missing_columns():
    """Non-destructive compatibility migration for databases from older releases.

    create_all() does not add columns to existing tables.  The storefront has
    evolved over several releases, so inspect every mapped table and add any
    missing scalar column as nullable.  Application-side defaults continue to
    supply values for new records, while existing rows remain readable.
    """
    inspector=inspect(db.engine)
    preparer=db.engine.dialect.identifier_preparer
    for table_name, table in db.metadata.tables.items():
        if not inspector.has_table(table_name):
            continue
        existing={c["name"] for c in inspector.get_columns(table_name)}
        for col in table.columns:
            if col.name in existing or col.primary_key:
                continue
            type_sql=col.type.compile(dialect=db.engine.dialect)
            qtable=preparer.quote(table_name); qcol=preparer.quote(col.name)
            db.session.execute(text(f"ALTER TABLE {qtable} ADD COLUMN {qcol} {type_sql}"))
    db.session.commit()


def create_app():
    base=os.path.abspath(os.path.join(os.path.dirname(__file__),".."))
    instance=os.path.join(base,"instance")
    os.makedirs(instance,exist_ok=True)
    app=Flask(__name__,instance_path=instance)
    app.config["SECRET_KEY"]=os.getenv("SECRET_KEY") or os.urandom(32).hex()
    db_url=os.getenv("DATABASE_URL") or ("sqlite:///"+os.path.join(instance,"niyaz_v2.db"))
    app.config["SQLALCHEMY_DATABASE_URI"]=db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
    app.config["MAX_CONTENT_LENGTH"]=int(os.getenv("MAX_UPLOAD_MB","8"))*1024*1024
    db.init_app(app)

    @app.errorhandler(500)
    def internal_server_error(error):
        # Keep the public response friendly while logging the real traceback for the developer.
        import logging, traceback
        try:
            log_dir=os.path.join(instance,"logs"); os.makedirs(log_dir,exist_ok=True)
            logging.basicConfig(filename=os.path.join(log_dir,"app.log"),level=logging.ERROR)
            logging.error("Internal Server Error\n%s", traceback.format_exc())
        except Exception:
            pass
        return "Internal Server Error", 500

    from .routes import main
    app.register_blueprint(main)

    @app.context_processor
    def globals_for_templates():
        from .models import User, Notification
        u=db.session.get(User,session.get("user_id")) if session.get("user_id") else None
        unread_count=Notification.query.filter_by(user_id=u.id,is_read=False).count() if u else 0
        return {
            "current_user":u,
            "notification_count":unread_count,
            "site_name":_setting("site.name","نیازتو"),
            "site_currency":_setting("site.currency","تومان"),
            "support_phone":_setting("site.support_phone","09055018315"),
            "support_email":_setting("site.support_email","پشتیبانی"),
            "shipping_fee":int(_setting("site.shipping_fee","0") or 0),
            "site_primary":_setting("theme.primary","#e50046"),
            "site_text":_setting("theme.text","#25262b"),
            "site_font":_setting("theme.font","Tahoma, Arial, sans-serif"),
            "site_primary2":_setting("theme.primary2","#c9003d"),
            "site_bg":_setting("theme.bg","#f5f6f8"),
            "site_card":_setting("theme.card","#ffffff"),
            "site_radius":_setting("theme.radius","18px"),
            "site_font_size":_setting("theme.font_size","14px"),
            "site_button_text":_setting("theme.button_text","#ffffff"),
            "site_logo_color":_setting("site.logo_color",""),
        }

    with app.app_context():
        from .models import User,Category,Product,Brand,Banner
        db.create_all()
        _add_missing_columns()
        seed()
    return app


def _setting(key,default=""):
    from .models import SiteSetting
    x=db.session.execute(db.select(SiteSetting).filter_by(key=key)).scalar_one_or_none()
    return x.value if x else default


def seed():
    from .models import User,Category,Product,Brand,Banner,SiteSetting
    from werkzeug.security import generate_password_hash
    admin=os.getenv("ADMIN_USERNAME", os.getenv("ADMIN_PHONE","09055018315")).strip()
    pw=os.getenv("ADMIN_PASSWORD","123456789")
    admin_phone=os.getenv("ADMIN_PHONE","09055018315").strip()
    if admin and pw and not User.query.filter_by(username=admin).first():
        db.session.add(User(username=admin,password_hash=generate_password_hash(pw),is_admin=True,role="admin",is_active=True))
    # Bootstrap administrator: create/sync the configured administrator account.
    # This is controlled by environment variables and never by a user's editable profile phone.
    if admin_phone and pw:
        from werkzeug.security import check_password_hash
        bootstrap=User.query.filter_by(phone=admin_phone).first()
        if not bootstrap:
            bootstrap=User.query.filter_by(username=admin_phone).first()
        if bootstrap:
            bootstrap.phone=admin_phone; bootstrap.username=admin_phone; bootstrap.is_admin=True; bootstrap.role="admin"; bootstrap.is_active=True
            if not check_password_hash(bootstrap.password_hash,pw):
                bootstrap.password_hash=generate_password_hash(pw)
        else:
            db.session.add(User(username=admin_phone,password_hash=generate_password_hash(pw),phone=admin_phone,is_admin=True,role="admin",is_active=True,full_name="مدیر سیستم"))

    defaults={
        "site.name":"نیازتو","site.logo_text":"نیازتو","site.currency":"تومان",
        "site.shipping_fee":"0","site.support_phone":"09055018315","site.support_email":"پشتیبانی نیازتو",
        "theme.primary":"#e50046","theme.primary2":"#c9003d","theme.text":"#25262b","theme.font":"Tahoma, Arial, sans-serif","theme.bg":"#f5f6f8","theme.card":"#ffffff","theme.radius":"18px","theme.font_size":"14px","theme.button_text":"#ffffff","site.logo_color":"",
    }
    for k,v in defaults.items():
        if not SiteSetting.query.filter_by(key=k).first(): db.session.add(SiteSetting(key=k,value=v))

    if Category.query.count()==0:
        cat_defs=[("دیجیتال","digital"),("موبایل","mobile"),("لپ‌تاپ","laptop"),("پوشاک","fashion"),("خانه و دکور","home"),("زیبایی","beauty"),("کتاب","book"),("ورزشی","sport")]
        cats=[Category(name=x,slug=x.lower().replace(" ","-"),icon=icon) for x,icon in cat_defs]
        db.session.add_all(cats); db.session.flush()
        db.session.add_all([
            Product(name="گوشی هوشمند نمونه",slug="sample-phone",description="گوشی نمونه برای شروع فروشگاه",price=12900000,compare_price=14900000,stock=20,category_id=cats[1].id,is_active=True),
            Product(name="لپ‌تاپ نمونه",slug="sample-laptop",description="لپ‌تاپ نمونه با مشخصات قابل ویرایش",price=38900000,stock=8,category_id=cats[2].id,is_active=True),
            Product(name="هودی نمونه",slug="sample-hoodie",description="محصول نمونه پوشاک",price=850000,stock=30,category_id=cats[3].id,is_active=True),
            Product(name="هدفون دیجیتال",slug="sample-headphone",description="محصول نمونه دیجیتال",price=1650000,stock=15,category_id=cats[0].id,is_active=True),
        ])
    icon_map={"دیجیتال":"digital","موبایل":"mobile","لپ‌تاپ":"laptop","پوشاک":"fashion","خانه و دکور":"home","زیبایی":"beauty","کتاب":"book","ورزشی":"sport"}
    for c in Category.query.all():
        if not c.icon or c.icon=="grid": c.icon=icon_map.get(c.name,"digital")

    if Brand.query.count()==0:
        db.session.add_all([Brand(name=x,slug=x.lower()) for x in ["Samsung","Apple","Xiaomi","Lenovo","Sony"]])
    db.session.commit()
