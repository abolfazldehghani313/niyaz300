from datetime import datetime
from . import db

class User(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    username=db.Column(db.String(80),unique=True,nullable=False)
    password_hash=db.Column(db.String(255),nullable=False)
    email=db.Column(db.String(160),default="")
    phone=db.Column(db.String(40),default="")
    full_name=db.Column(db.String(160),default="")
    role=db.Column(db.String(30),default="customer")
    is_admin=db.Column(db.Boolean,default=False)
    is_active=db.Column(db.Boolean,default=True)
    created_at=db.Column(db.DateTime,default=datetime.utcnow)


class OTPChallenge(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    phone=db.Column(db.String(40),nullable=False)
    code_hash=db.Column(db.String(255),nullable=False)
    purpose=db.Column(db.String(30),default="register")
    attempts=db.Column(db.Integer,default=0)
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    expires_at=db.Column(db.DateTime,nullable=False)
    used_at=db.Column(db.DateTime)

class Seller(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    store_name=db.Column(db.String(160),nullable=False)
    commission_percent=db.Column(db.Integer,default=0)
    balance=db.Column(db.Integer,default=0)
    active=db.Column(db.Boolean,default=True)
    user=db.relationship("User",backref="seller_profile")

class Category(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(120),nullable=False)
    slug=db.Column(db.String(140),unique=True,nullable=False)
    parent_id=db.Column(db.Integer,db.ForeignKey("category.id"))
    image=db.Column(db.String(255),default="")
    icon=db.Column(db.String(80),default="grid")
    is_active=db.Column(db.Boolean,default=True)
    products=db.relationship("Product",backref="category",lazy=True)

class Brand(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(120),unique=True,nullable=False)
    slug=db.Column(db.String(140),unique=True,nullable=False)
    logo=db.Column(db.String(255),default="")
    is_active=db.Column(db.Boolean,default=True)
    products=db.relationship("Product",backref="brand",lazy=True)

class Product(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(180),nullable=False)
    slug=db.Column(db.String(220),unique=True,nullable=False)
    description=db.Column(db.Text,default="")
    price=db.Column(db.Integer,nullable=False)
    compare_price=db.Column(db.Integer,default=0)
    stock=db.Column(db.Integer,default=0)
    sku=db.Column(db.String(80),default="")
    image=db.Column(db.String(255),default="")
    category_id=db.Column(db.Integer,db.ForeignKey("category.id"))
    brand_id=db.Column(db.Integer,db.ForeignKey("brand.id"),nullable=True)
    seller_id=db.Column(db.Integer,db.ForeignKey("seller.id"),nullable=True)
    attributes=db.Column(db.Text,default="{}")
    is_active=db.Column(db.Boolean,default=True)
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    images=db.relationship("ProductImage",backref="product",cascade="all,delete-orphan")
    variants=db.relationship("ProductVariant",backref="product",cascade="all,delete-orphan")
    seller=db.relationship("Seller",backref="products")

class ProductImage(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    product_id=db.Column(db.Integer,db.ForeignKey("product.id"),nullable=False)
    filename=db.Column(db.String(255),nullable=False)
    sort_order=db.Column(db.Integer,default=0)

class ProductVariant(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    product_id=db.Column(db.Integer,db.ForeignKey("product.id"),nullable=False)
    name=db.Column(db.String(180),nullable=False)
    sku=db.Column(db.String(80),default="")
    price=db.Column(db.Integer,nullable=False)
    stock=db.Column(db.Integer,default=0)
    attributes=db.Column(db.Text,default="{}")
    active=db.Column(db.Boolean,default=True)

class Coupon(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    code=db.Column(db.String(80),unique=True,nullable=False)
    discount_type=db.Column(db.String(20),default="percent")
    value=db.Column(db.Integer,default=0)
    min_total=db.Column(db.Integer,default=0)
    max_discount=db.Column(db.Integer,default=0)
    starts_at=db.Column(db.DateTime)
    ends_at=db.Column(db.DateTime)
    usage_limit=db.Column(db.Integer,default=0)
    used_count=db.Column(db.Integer,default=0)
    active=db.Column(db.Boolean,default=True)

class Order(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    subtotal=db.Column(db.Integer,default=0)
    discount=db.Column(db.Integer,default=0)
    coupon_code=db.Column(db.String(80),default="")
    shipping_fee=db.Column(db.Integer,default=0)
    total=db.Column(db.Integer,default=0)
    status=db.Column(db.String(40),default="pending")
    payment_status=db.Column(db.String(40),default="unpaid")
    payment_provider=db.Column(db.String(80),default="")
    payment_authority=db.Column(db.String(255),default="")
    shipping_name=db.Column(db.String(160),default="")
    shipping_phone=db.Column(db.String(40),default="")
    shipping_address=db.Column(db.Text,default="")
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    user=db.relationship("User",backref="orders")
    items=db.relationship("OrderItem",backref="order",cascade="all,delete-orphan")

class OrderItem(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    order_id=db.Column(db.Integer,db.ForeignKey("order.id"),nullable=False)
    product_id=db.Column(db.Integer,db.ForeignKey("product.id"),nullable=False)
    variant_id=db.Column(db.Integer,db.ForeignKey("product_variant.id"))
    name=db.Column(db.String(180),nullable=False)
    price=db.Column(db.Integer,nullable=False)
    quantity=db.Column(db.Integer,default=1)
    product=db.relationship("Product")
    variant=db.relationship("ProductVariant")

class PaymentTransaction(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    order_id=db.Column(db.Integer,db.ForeignKey("order.id"),nullable=False)
    provider=db.Column(db.String(80),nullable=False)
    amount=db.Column(db.Integer,nullable=False)
    authority=db.Column(db.String(255),default="")
    reference=db.Column(db.String(255),default="")
    status=db.Column(db.String(40),default="pending")
    raw_callback=db.Column(db.Text,default="")
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    verified_at=db.Column(db.DateTime)

class SiteSetting(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    key=db.Column(db.String(160),unique=True,nullable=False)
    value=db.Column(db.Text,default="")

class Wishlist(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    product_id=db.Column(db.Integer,db.ForeignKey("product.id"),nullable=False)
    __table_args__=(db.UniqueConstraint("user_id","product_id"),)

class Notification(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    title=db.Column(db.String(180),nullable=False)
    message=db.Column(db.Text,default="")
    is_read=db.Column(db.Boolean,default=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    user=db.relationship("User",backref="notifications")

class SupportTicket(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    subject=db.Column(db.String(180),nullable=False)
    status=db.Column(db.String(30),default="open")
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    updated_at=db.Column(db.DateTime,default=datetime.utcnow)
    user=db.relationship("User",backref="support_tickets")
    messages=db.relationship("SupportMessage",backref="ticket",cascade="all,delete-orphan",order_by="SupportMessage.created_at")

class SupportMessage(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    ticket_id=db.Column(db.Integer,db.ForeignKey("support_ticket.id"),nullable=False)
    sender_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    message=db.Column(db.Text,nullable=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    sender=db.relationship("User")

class Review(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    product_id=db.Column(db.Integer,db.ForeignKey("product.id"),nullable=False)
    rating=db.Column(db.Integer,nullable=False,default=5)
    comment=db.Column(db.Text,default="")
    status=db.Column(db.String(20),default="pending")
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    user=db.relationship("User",backref="reviews")
    product=db.relationship("Product",backref="reviews")
    __table_args__=(db.UniqueConstraint("user_id","product_id",name="uq_review_user_product"),)

class Banner(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    title=db.Column(db.String(180),default="")
    subtitle=db.Column(db.String(255),default="")
    image=db.Column(db.String(255),default="")
    link=db.Column(db.String(500),default="")
    kind=db.Column(db.String(30),default="slider")
    sort_order=db.Column(db.Integer,default=0)
    is_active=db.Column(db.Boolean,default=True)
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
